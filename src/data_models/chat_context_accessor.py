# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import logging
from datetime import datetime, timezone
from time import time

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob.aio import BlobServiceClient
from semantic_kernel.contents import ChatMessageContent, AuthorRole, TextContent

from data_models.chat_context import ChatContext, PatientContext

logger = logging.getLogger(__name__)

# Current schema version for migration support
CURRENT_SCHEMA_VERSION = 2


class ChatContextAccessor:
    """
    Hybrid context accessor - supports both session-only and patient-specific contexts.

    ChatContext lifecycle:

    **Session Context (no patient isolation):**
    1. User sends a message to Agent.
    2. Agent loads ChatContext from blob storage using conversation_id only.
    - File: `{conversation_id}/session_context.json`
    - If found, reads existing ChatContext; otherwise creates new one.
    3. Agent processes message and sends responses to User.
    4. Save ChatContext to `session_context.json`.
    5. Repeat steps 1-4 for the entire conversation.
    6. User sends a "clear" message.
    7. Archive ChatContext:
    - Save to `{timestamp}_session_archived.json`
    - Delete original `session_context.json`

    **Patient Context (with patient isolation):**
    1. User mentions a patient ID or system detects patient context.
    2. Agent loads ChatContext using conversation_id AND patient_id.
    - File: `{conversation_id}/patient_{patient_id}_context.json`
    - If found, reads existing patient-specific context; otherwise creates new one.
    3. Agent processes message with patient context isolation.
    4. Save ChatContext to `patient_{patient_id}_context.json`.
    5. Repeat steps 1-4 for patient-specific conversation.
    6. When switching patients or clearing:
    - Archive current patient context to `{timestamp}_patient_{patient_id}_archived.json`
    - Delete original patient context file.

    Key functionality:
    - Patient isolation: separate files for each patient (patient_{id}_context.json)
    - Session context: shared conversation state (session_context.json)
    - Automatic patient context detection and switching
    - Chat history isolation per patient
    - Migration support for legacy files
    - Backward compatibility with main branch structure
    """

    def __init__(
        self,
        blob_service_client: BlobServiceClient,
        container_name: str = "chat-sessions",
        cognitive_services_token_provider=None,
    ):
        self.blob_service_client = blob_service_client
        self.container_client = blob_service_client.get_container_client(container_name)
        self.cognitive_services_token_provider = cognitive_services_token_provider

    def get_blob_path(self, conversation_id: str, patient_id: str = None) -> str:
        """Get blob path for patient-specific or session context."""
        if patient_id:
            return f"{conversation_id}/patient_{patient_id}_context.json"
        return f"{conversation_id}/session_context.json"

    async def read(self, conversation_id: str, patient_id: str = None) -> ChatContext:
        """Read chat context for conversation/patient."""
        start = time()
        try:
            blob_path = self.get_blob_path(conversation_id, patient_id)
            blob_client = self.container_client.get_blob_client(blob_path)
            blob = await blob_client.download_blob()
            blob_str = await blob.readall()
            decoded_str = blob_str.decode("utf-8")
            context = self.deserialize(decoded_str)

            # Ensure patient context is properly set up
            if patient_id:
                context.patient_id = patient_id
                if patient_id not in context.patient_contexts:
                    context.patient_contexts[patient_id] = PatientContext(patient_id=patient_id)
            else:
                context.patient_id = None

            return context

        except ResourceNotFoundError:
            logger.info(f"Creating new context for {conversation_id}/{patient_id or 'session'}")
            context = ChatContext(conversation_id)
            if patient_id:
                context.patient_id = patient_id
                context.patient_contexts[patient_id] = PatientContext(patient_id=patient_id)
            return context
        except Exception as e:
            logger.warning(f"Failed to read context for {conversation_id}/{patient_id or 'session'}: {e}")
            context = ChatContext(conversation_id)
            if patient_id:
                context.patient_id = patient_id
                context.patient_contexts[patient_id] = PatientContext(patient_id=patient_id)
            return context
        finally:
            logger.info(
                f"Read ChatContext for {conversation_id}/{patient_id or 'session'}. Duration: {time() - start}s"
            )

    async def write(self, chat_ctx: ChatContext) -> None:
        """Write chat context to appropriate file."""
        start = time()
        try:
            blob_path = self.get_blob_path(chat_ctx.conversation_id, chat_ctx.patient_id)
            blob_client = self.container_client.get_blob_client(blob_path)
            blob_str = self.serialize(chat_ctx)
            await blob_client.upload_blob(blob_str, overwrite=True)
        finally:
            logger.info(
                f"Wrote ChatContext for {chat_ctx.conversation_id}/{chat_ctx.patient_id or 'session'}. Duration: {time() - start}s"
            )

    async def archive(self, chat_ctx: ChatContext) -> None:
        """Archive chat context with timestamp."""
        start = time()
        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            if chat_ctx.patient_id:
                archive_blob_path = f"{chat_ctx.conversation_id}/{timestamp}_patient_{chat_ctx.patient_id}_archived.json"
            else:
                archive_blob_path = f"{chat_ctx.conversation_id}/{timestamp}_session_archived.json"

            archive_blob_str = self.serialize(chat_ctx)
            await self.container_client.upload_blob(archive_blob_path, archive_blob_str, overwrite=True)

            blob_path = self.get_blob_path(chat_ctx.conversation_id, chat_ctx.patient_id)
            await self.container_client.delete_blob(blob_path)
        except ResourceNotFoundError:
            pass  # File already deleted or never existed
        finally:
            logger.info(
                f"Archived ChatContext for {chat_ctx.conversation_id}/{chat_ctx.patient_id or 'session'}. Duration: {time() - start}s"
            )

    async def archive_to_folder(self, conversation_id: str, patient_id: str, archive_folder: str) -> None:
        """Archive context to specific folder structure."""
        start = time()
        try:
            current_blob_path = self.get_blob_path(conversation_id, patient_id)
            try:
                blob_client = self.container_client.get_blob_client(current_blob_path)
                blob = await blob_client.download_blob()
                blob_str = await blob.readall()

                timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                if patient_id:
                    archive_blob_path = "%s/%s/%s_patient_%s_archived.json" % (
                        archive_folder, conversation_id, timestamp, patient_id)
                else:
                    archive_blob_path = "%s/%s/%s_session_archived.json" % (archive_folder, conversation_id, timestamp)

                await self.container_client.upload_blob(archive_blob_path, blob_str, overwrite=True)
                await blob_client.delete_blob()

                logger.info("Archived context to %s", archive_blob_path)
            except ResourceNotFoundError:
                logger.warning("No context found to archive for %s/%s", conversation_id, patient_id or 'session')
        except Exception as e:
            logger.error("Failed to archive context for %s/%s: %s", conversation_id, patient_id or 'session', e)
        finally:
            logger.info("Archive operation for %s/%s completed. Duration: %ss",
                        conversation_id, patient_id or 'session', time() - start)

    @staticmethod
    def serialize(chat_ctx: ChatContext) -> str:
        """Serialize chat context to JSON."""
        # Extract chat history with proper schema
        chat_messages = []
        for msg in chat_ctx.chat_history.messages:
            if hasattr(msg, 'items') and msg.items:
                content = msg.items[0].text if hasattr(msg.items[0], 'text') else str(msg.items[0])
            else:
                content = str(msg.content) if hasattr(msg, 'content') else ""

            chat_messages.append({
                "role": msg.role.value,
                "content": content,
                "name": getattr(msg, 'name', None)
            })

        # REMOVED: patient_contexts serialization - use registry instead!

        data = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "conversation_id": chat_ctx.conversation_id,
            "patient_id": chat_ctx.patient_id,
            # REMOVED: "patient_contexts": patient_contexts,
            "workflow_summary": getattr(chat_ctx, 'workflow_summary', None),
            "chat_history": chat_messages,
            "patient_data": chat_ctx.patient_data,
            "display_blob_urls": chat_ctx.display_blob_urls,
            "display_image_urls": getattr(chat_ctx, 'display_image_urls', []),
            "display_clinical_trials": chat_ctx.display_clinical_trials,
            "output_data": chat_ctx.output_data,
            "healthcare_agents": chat_ctx.healthcare_agents,
        }
        return json.dumps(data, indent=2, default=str)

    @staticmethod
    def deserialize(data_str: str) -> ChatContext:
        """Deserialize chat context from JSON with migration support."""
        data = json.loads(data_str)
        schema_version = data.get("schema_version", 1)

        context = ChatContext(data["conversation_id"])
        context.patient_id = data.get("patient_id")

        # REMOVED: patient_contexts restoration - load from registry instead!
        # Legacy support for old files that still have patient_contexts
        if "patient_contexts" in data:
            logger.info("Found legacy patient_contexts in context file - consider migrating to registry-only")

        context.workflow_summary = data.get("workflow_summary")

        # Process chat history (unchanged)
        for msg_data in data.get("chat_history", []):
            if "role" not in msg_data:
                logger.warning("Skipping message with no role: %s", msg_data.keys())
                continue

            role = AuthorRole(msg_data["role"])
            name = msg_data.get("name")

            if "content" in msg_data:
                content_str = msg_data["content"]
            elif "items" in msg_data and msg_data["items"]:
                content_str = msg_data["items"][0].get("text", "")
            else:
                logger.warning("Skipping message with no content: %s", msg_data)
                continue

            if role == AuthorRole.TOOL and not content_str:
                logger.warning("Skipping empty tool message")
                continue

            msg = ChatMessageContent(
                role=role,
                items=[TextContent(text=str(content_str))],
            )
            if name:
                msg.name = name
            context.chat_history.messages.append(msg)

        # Restore other fields (unchanged)
        context.patient_data = data.get("patient_data", [])
        context.display_blob_urls = data.get("display_blob_urls", [])
        context.display_image_urls = data.get("display_image_urls", [])
        context.display_clinical_trials = data.get("display_clinical_trials", [])
        context.output_data = data.get("output_data", [])
        context.healthcare_agents = data.get("healthcare_agents", {})

        if schema_version < CURRENT_SCHEMA_VERSION:
            logger.info("Migrated context from schema v%s to v%s", schema_version, CURRENT_SCHEMA_VERSION)

        return context

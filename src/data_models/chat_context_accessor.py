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
from services.patient_context_service import PATIENT_CONTEXT_PREFIX  # reuse constant

logger = logging.getLogger(__name__)


class ChatContextAccessor:
    """
    Accessor for reading and writing chat context to Azure Blob Storage.

    ChatContext lifecycle:

    1. User sends a message to Agent.
    2. Agent load ChatContext from blob storage using conversation_id.
        - If found, it reads the existing ChatContext from blob storage.
        - Otherwise, it creates a new ChatContext with the given conversation_id.
    2. Agent sends responses to User.
    3. Save ChatContext to blob storage as `chat_context.json`.
    4. Repeat steps 1-3 for the entire conversation.
    5. User sends a "clear" message.
    6. Archive ChatHistory to the blob storage.
        - Append the "clear" message to chat history.
        - Save ChatContext to `{datetime}_chat_context.json`.
        - Delete `chat_context.json`
    7. Hybrid accessor supporting session + per-patient isolation.
    8. Ephemeral PATIENT_CONTEXT_JSON system messages are stripped (never persisted).
    """

    def __init__(self, blob_service_client: BlobServiceClient, container_name: str = "chat-sessions",):
        self.blob_service_client = blob_service_client
        self.container_client = blob_service_client.get_container_client(container_name)

    def get_blob_path(self, conversation_id: str, patient_id: str = None) -> str:
        if patient_id:
            return f"{conversation_id}/patient_{patient_id}_context.json"
        return f"{conversation_id}/session_context.json"

    async def read(self, conversation_id: str, patient_id: str = None) -> ChatContext:
        start = time()
        try:
            blob_path = self.get_blob_path(conversation_id, patient_id)
            blob_client = self.container_client.get_blob_client(blob_path)
            blob = await blob_client.download_blob()
            decoded_str = (await blob.readall()).decode("utf-8")
            context = self.deserialize(decoded_str)

            if patient_id:
                context.patient_id = patient_id
                if patient_id not in context.patient_contexts:
                    context.patient_contexts[patient_id] = PatientContext(patient_id=patient_id)
            else:
                context.patient_id = None
            return context
        except ResourceNotFoundError:
            context = ChatContext(conversation_id)
            if patient_id:
                context.patient_id = patient_id
                context.patient_contexts[patient_id] = PatientContext(patient_id=patient_id)
            return context
        except Exception as e:
            logger.warning("Failed to read context %s/%s: %s",
                           conversation_id, patient_id or "session", e)
            context = ChatContext(conversation_id)
            if patient_id:
                context.patient_id = patient_id
                context.patient_contexts[patient_id] = PatientContext(patient_id=patient_id)
            return context
        finally:
            logger.info("Read ChatContext %s/%s in %.3fs",
                        conversation_id, patient_id or "session", time() - start)

    async def write(self, chat_ctx: ChatContext) -> None:
        start = time()
        try:
            blob_path = self.get_blob_path(chat_ctx.conversation_id, chat_ctx.patient_id)
            blob_client = self.container_client.get_blob_client(blob_path)
            await blob_client.upload_blob(self.serialize(chat_ctx), overwrite=True)
        finally:
            logger.info("Wrote ChatContext %s/%s in %.3fs",
                        chat_ctx.conversation_id, chat_ctx.patient_id or "session", time() - start)

    async def archive(self, chat_ctx: ChatContext) -> None:
        start = time()
        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            if chat_ctx.patient_id:
                archive_blob_path = f"{chat_ctx.conversation_id}/{timestamp}_patient_{chat_ctx.patient_id}_archived.json"
            else:
                archive_blob_path = f"{chat_ctx.conversation_id}/{timestamp}_session_archived.json"

            await self.container_client.upload_blob(archive_blob_path, self.serialize(chat_ctx), overwrite=True)
            blob_path = self.get_blob_path(chat_ctx.conversation_id, chat_ctx.patient_id)
            try:
                await self.container_client.delete_blob(blob_path)
            except ResourceNotFoundError:
                pass
        finally:
            logger.info("Archived ChatContext %s/%s in %.3fs",
                        chat_ctx.conversation_id, chat_ctx.patient_id or "session", time() - start)

    async def archive_to_folder(self, conversation_id: str, patient_id: str, archive_folder: str) -> None:
        start = time()
        try:
            current_blob_path = self.get_blob_path(conversation_id, patient_id)
            blob_client = self.container_client.get_blob_client(current_blob_path)
            try:
                blob = await blob_client.download_blob()
                data = await blob.readall()

                timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                if patient_id:
                    archive_blob_path = f"{archive_folder}/{conversation_id}/{timestamp}_patient_{patient_id}_archived.json"
                else:
                    archive_blob_path = f"{archive_folder}/{conversation_id}/{timestamp}_session_archived.json"

                await self.container_client.upload_blob(archive_blob_path, data, overwrite=True)
                await blob_client.delete_blob()
                logger.info("Archived %s", archive_blob_path)
            except ResourceNotFoundError:
                logger.warning("Nothing to archive for %s/%s", conversation_id, patient_id or "session")
        except Exception as e:
            logger.error("Archive to folder failed %s/%s: %s", conversation_id, patient_id or "session", e)
        finally:
            logger.info("Archive-to-folder %s/%s finished in %.3fs",
                        conversation_id, patient_id or "session", time() - start)

    @staticmethod
    def serialize(chat_ctx: ChatContext) -> str:
        chat_messages = []
        skipped_pc = 0
        for msg in chat_ctx.chat_history.messages:
            if hasattr(msg, "items") and msg.items:
                content = msg.items[0].text if hasattr(msg.items[0], "text") else str(msg.items[0])
            else:
                content = str(getattr(msg, "content", "") or "")

            # Skip ephemeral patient context snapshot
            if msg.role == AuthorRole.SYSTEM and content.startswith(PATIENT_CONTEXT_PREFIX):
                skipped_pc += 1
                continue

            chat_messages.append({
                "role": msg.role.value,
                "content": content,
                "name": getattr(msg, "name", None)
            })

        if skipped_pc:
            logger.debug("Filtered %d PATIENT_CONTEXT_JSON system message(s) from serialization", skipped_pc)

        data = {
            "conversation_id": chat_ctx.conversation_id,
            "patient_id": chat_ctx.patient_id,
            "chat_history": chat_messages,
            "patient_data": chat_ctx.patient_data,
            "display_blob_urls": chat_ctx.display_blob_urls,
            "display_image_urls": getattr(chat_ctx, "display_image_urls", []),
            "display_clinical_trials": chat_ctx.display_clinical_trials,
            "output_data": chat_ctx.output_data,
            "healthcare_agents": chat_ctx.healthcare_agents,
        }
        return json.dumps(data, indent=2, default=str)

    @staticmethod
    def deserialize(data_str: str) -> ChatContext:
        data = json.loads(data_str)
        context = ChatContext(data["conversation_id"])
        context.patient_id = data.get("patient_id")

        for msg_data in data.get("chat_history", []):
            role_val = msg_data.get("role")
            if not role_val:
                continue
            role = AuthorRole(role_val)
            content_str = msg_data.get("content", "")
            # Defensive skip in case an old file contained ephemeral snapshot
            if role == AuthorRole.SYSTEM and content_str.startswith(PATIENT_CONTEXT_PREFIX):
                continue
            if role == AuthorRole.TOOL and not content_str:
                continue
            msg = ChatMessageContent(
                role=role,
                items=[TextContent(text=str(content_str))]
            )
            name = msg_data.get("name")
            if name:
                msg.name = name
            context.chat_history.messages.append(msg)

        context.patient_data = data.get("patient_data", [])
        context.display_blob_urls = data.get("display_blob_urls", [])
        context.display_image_urls = data.get("display_image_urls", [])
        context.display_clinical_trials = data.get("display_clinical_trials", [])
        context.output_data = data.get("output_data", [])
        context.healthcare_agents = data.get("healthcare_agents", {})
        return context

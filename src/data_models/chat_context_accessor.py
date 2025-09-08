# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import logging
from datetime import datetime, timezone
from time import time

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob.aio import BlobServiceClient
from semantic_kernel.contents.chat_history import ChatHistory

from data_models.chat_context import ChatContext, PatientContext

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
    """

    def __init__(self, blob_service_client: BlobServiceClient, container_name: str = "chat-sessions",):
        self.blob_service_client = blob_service_client
        self.container_client = blob_service_client.get_container_client(container_name)

    def get_blob_path(self, conversation_id: str) -> str:
        return f"{conversation_id}/chat_context.json"

    async def read(self, conversation_id: str) -> ChatContext:
        """Read the chat context for a given conversation ID."""
        start = time()
        try:
            blob_path = self.get_blob_path(conversation_id)
            blob_client = self.container_client.get_blob_client(blob_path)
            blob = await blob_client.download_blob()
            blob_str = await blob.readall()
            decoded_str = blob_str.decode("utf-8")
            return self.deserialize(decoded_str)
        except:
            return ChatContext(conversation_id)
        finally:
            logger.info(f"Read ChatContext for {conversation_id}. Duration: {time() - start}s")

    async def write(self, chat_ctx: ChatContext) -> None:
        """Write the chat context for a given conversation ID."""
        start = time()
        try:
            blob_path = self.get_blob_path(chat_ctx.conversation_id)
            blob_client = self.container_client.get_blob_client(blob_path)
            blob_str = self.serialize(chat_ctx)
            await blob_client.upload_blob(blob_str, overwrite=True)
        finally:
            logger.info(f"Wrote ChatContext for {chat_ctx.conversation_id}. Duration: {time() - start}s")

    async def archive(self, chat_ctx: ChatContext) -> None:
        """Archive the chat context for a given conversation ID by renaming the blob."""
        start = time()
        try:
            # Archive the chat context
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            archive_blob_path = f"{chat_ctx.conversation_id}/{timestamp}_chat_context.json"
            archive_blob_str = self.serialize(chat_ctx)
            await self.container_client.upload_blob(archive_blob_path, archive_blob_str, overwrite=True)

            # Delete the original chat context
            blob_path = self.get_blob_path(chat_ctx.conversation_id)
            await self.container_client.delete_blob(blob_path)
        except ResourceNotFoundError:
            # If the blob is not found, it means it has already been deleted or never existed.
            pass
        finally:
            logger.info(f"Archive ran for {chat_ctx.conversation_id}. Duration: {time() - start}s")

    @staticmethod
    def serialize(chat_ctx: ChatContext) -> str:
        """Serialize the chat context to a string."""
        return json.dumps(
            {
                "conversation_id": chat_ctx.conversation_id,
                "chat_history": chat_ctx.chat_history.serialize(),
                "patient_id": chat_ctx.patient_id,
                "patient_data": chat_ctx.patient_data,
                "patient_contexts": {
                    pid: {
                        "patient_id": pctx.patient_id,
                        "facts": pctx.facts
                    } for pid, pctx in chat_ctx.patient_contexts.items()
                },                
                "display_blob_urls": chat_ctx.display_blob_urls,
                "display_clinical_trials": chat_ctx.display_clinical_trials,
                "output_data": chat_ctx.output_data,
                "healthcare_agents": chat_ctx.healthcare_agents,
            },
            indent=2,
        )

    @staticmethod
    def deserialize(data_str: str) -> ChatContext:
        """Deserialize the chat context from a string."""
        data = json.loads(data_str)
        ctx = ChatContext(data["conversation_id"])
        ctx.chat_history = ChatHistory.restore_chat_history(data["chat_history"])
        ctx.patient_id = data["patient_id"]
        for pid, stored in (data.get("patient_contexts") or {}).items():
            ctx.patient_contexts[pid] = PatientContext(
                patient_id=stored.get("patient_id", pid),
                facts=stored.get("facts", {}) or {}
            )
        ctx.patient_data = data["patient_data"]
        ctx.display_blob_urls = data["display_blob_urls"]
        ctx.display_clinical_trials = data["display_clinical_trials"]
        ctx.output_data = data["output_data"]
        ctx.healthcare_agents = data.get("healthcare_agents", {})
        return ctx

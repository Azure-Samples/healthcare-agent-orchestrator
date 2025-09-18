# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from botbuilder.core import MessageFactory, TurnContext
from botbuilder.core.teams import TeamsActivityHandler
from botbuilder.integration.aiohttp import CloudAdapter
from botbuilder.schema import Activity, ActivityTypes
from semantic_kernel.agents import AgentGroupChat

from semantic_kernel.contents import AuthorRole, ChatMessageContent, TextContent
from services.patient_context_service import PATIENT_CONTEXT_PREFIX

from data_models.app_context import AppContext
from data_models.chat_context import ChatContext

from errors import NotAuthorizedError
from group_chat import create_group_chat
from services.patient_context_service import PatientContextService
from services.patient_context_analyzer import PatientContextAnalyzer


logger = logging.getLogger(__name__)


class AssistantBot(TeamsActivityHandler):
    def __init__(
        self,
        agent: dict,
        turn_contexts: dict[str, dict[str, TurnContext]],
        adapters: dict[str, CloudAdapter],
        app_context: AppContext
    ):
        self.app_context = app_context
        self.all_agents = app_context.all_agent_configs
        self.name = agent["name"]
        self.turn_contexts = turn_contexts
        self.adapters = adapters
        self.adapters[self.name].on_turn_error = self.on_error
        self.data_access = app_context.data_access
        self.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Add patient context service
        analyzer = PatientContextAnalyzer(token_provider=app_context.cognitive_services_token_provider)
        self.patient_context_service = PatientContextService(
            analyzer=analyzer,
            registry_accessor=app_context.data_access.patient_context_registry_accessor,
            context_accessor=app_context.data_access.chat_context_accessor
        )

    async def get_bot_context(
        self, conversation_id: str, bot_name: str, turn_context: TurnContext
    ):
        if conversation_id not in self.turn_contexts:
            self.turn_contexts[conversation_id] = {}

        if bot_name not in self.turn_contexts[conversation_id]:
            context = await self.create_turn_context(bot_name, turn_context)
            self.turn_contexts[conversation_id][bot_name] = context

        return self.turn_contexts[conversation_id][bot_name]

    async def create_turn_context(self, bot_name, turn_context):
        app_id = next(
            agent["bot_id"] for agent in self.all_agents if agent["name"] == bot_name
        )

        # Lookup adapter for bot_name. bot_name maybe different from self.name.
        adapter = self.adapters[bot_name]
        claims_identity = adapter.create_claims_identity(app_id)
        connector_factory = (
            adapter.bot_framework_authentication.create_connector_factory(
                claims_identity
            )
        )
        connector_client = await connector_factory.create(
            turn_context.activity.service_url, "https://api.botframework.com"
        )
        user_token_client = (
            await adapter.bot_framework_authentication.create_user_token_client(
                claims_identity
            )
        )

        async def logic(context: TurnContext):
            pass

        context = TurnContext(adapter, turn_context.activity)
        context.turn_state[CloudAdapter.BOT_IDENTITY_KEY] = claims_identity
        context.turn_state[CloudAdapter.BOT_CONNECTOR_CLIENT_KEY] = connector_client
        context.turn_state[CloudAdapter.USER_TOKEN_CLIENT_KEY] = user_token_client
        context.turn_state[CloudAdapter.CONNECTOR_FACTORY_KEY] = connector_factory
        context.turn_state[CloudAdapter.BOT_OAUTH_SCOPE_KEY] = "https://api.botframework.com/.default"
        context.turn_state[CloudAdapter.BOT_CALLBACK_HANDLER_KEY] = logic

        return context

    async def _handle_clear_command(self, content: str, chat_ctx: ChatContext, conversation_id: str) -> bool:
        """Handle patient context clear commands - aligned with web interface."""
        content_lower = content.lower().strip()
        if content_lower in ["clear", "clear patient", "clear context", "clear patient context"]:
            logger.info(f"Processing clear command for conversation: {conversation_id}")

            # Archive everything before clearing (same as web interface)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
            archive_folder = f"archive/{timestamp}"

            try:
                logger.info(f"Starting archive to folder: {archive_folder}")

                # Archive session context (this creates the archive folder structure)
                await self.data_access.chat_context_accessor.archive_to_folder(conversation_id, None, archive_folder)
                logger.info(f"Archived session context to {archive_folder}")

                # Archive ALL patient contexts (not just from chat_ctx.patient_contexts)
                # We need to get the list from the registry like the web interface does
                try:
                    patient_registry, _ = await self.patient_context_service.registry_accessor.read_registry(conversation_id)
                    if patient_registry:
                        for patient_id in patient_registry.keys():
                            await self.data_access.chat_context_accessor.archive_to_folder(conversation_id, patient_id, archive_folder)
                            logger.info(f"Archived patient context for {patient_id} to {archive_folder}")
                except Exception as registry_error:
                    logger.warning(f"Could not read registry for archiving patient contexts: {registry_error}")
                    # Fallback: use patient_contexts from chat_ctx if available
                    if hasattr(chat_ctx, 'patient_contexts') and chat_ctx.patient_contexts:
                        for patient_id in chat_ctx.patient_contexts.keys():
                            await self.data_access.chat_context_accessor.archive_to_folder(conversation_id, patient_id, archive_folder)
                            logger.info(f"Archived patient context for {patient_id} to {archive_folder} (fallback)")

                # Archive patient registry (this renames it, doesn't create folder structure)
                await self.patient_context_service.registry_accessor.archive_registry(conversation_id)
                logger.info(f"Archived patient registry for {conversation_id}")

                # Clear chat context (same as web interface)
                chat_ctx.patient_context = None
                if hasattr(chat_ctx, 'patient_contexts'):
                    chat_ctx.patient_contexts.clear()
                chat_ctx.chat_history.clear()
                chat_ctx.patient_id = None

                # Save the cleared context
                await self.data_access.chat_context_accessor.write(chat_ctx)
                logger.info(f"Saved cleared context for {conversation_id}")

                logger.info(f"Successfully archived and cleared all contexts to {archive_folder}")
                return True

            except Exception as e:
                logger.error(f"Failed to archive contexts during clear: {e}")
                # Still clear the context even if archiving fails
                chat_ctx.patient_context = None
                if hasattr(chat_ctx, 'patient_contexts'):
                    chat_ctx.patient_contexts.clear()
                chat_ctx.chat_history.clear()
                chat_ctx.patient_id = None

                # Save the cleared context
                try:
                    await self.data_access.chat_context_accessor.write(chat_ctx)
                    logger.info(f"Saved cleared context after archive failure")
                except Exception as save_error:
                    logger.error(f"Failed to save cleared context: {save_error}")

                return True

        return False

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        conversation_id = turn_context.activity.conversation.id
        chat_context_accessor = self.data_access.chat_context_accessor
        chat_artifact_accessor = self.data_access.chat_artifact_accessor  # Main branch addition

        # Extract raw user text (without bot mention) once
        raw_user_text = turn_context.remove_recipient_mention(turn_context.activity).strip()

        # STEP 1: Load session context first
        try:
            chat_ctx = await chat_context_accessor.read(conversation_id, None)
            if not chat_ctx:
                chat_ctx = ChatContext(conversation_id)
                logger.info(f"Created new session context for: {conversation_id}")
            else:
                logger.info(f"Loaded existing session context for: {conversation_id}")
        except Exception as e:
            logger.error(f"Failed to load session context: {e}")
            chat_ctx = ChatContext(conversation_id)

        # STEP 1.5: Handle clear commands (main branch logic enhanced with patient context)
        if await self._handle_clear_command(raw_user_text, chat_ctx, conversation_id):
            # Also archive chat artifacts (main branch functionality)
            await chat_artifact_accessor.archive(conversation_id)
            await turn_context.send_activity("Conversation cleared!")
            return

        # STEP 2: Patient context decision and application
        decision, timing = await self.patient_context_service.decide_and_apply(raw_user_text, chat_ctx)

        logger.info(f"Patient context decision: {decision} | Patient: {chat_ctx.patient_id} | Timing: {timing}")

        # STEP 3: Handle special decision outcomes
        if decision == "CLEAR":
            # This should now be handled by _handle_clear_command above, but keep as fallback
            await chat_artifact_accessor.archive(conversation_id)
            await turn_context.send_activity("All contexts have been archived and cleared. How can I assist you today?")
            return
        elif decision == "NEEDS_PATIENT_ID":
            await turn_context.send_activity(
                "I need a patient ID to proceed. Please provide the patient ID in the format 'patient_X' "
                "(e.g., '@Orchestrator start tumor board review for patient_4')."
            )
            return
        elif decision == "RESTORED_FROM_STORAGE":
            logger.info(f"Restored patient context from storage: {chat_ctx.patient_id}")

        # NEW: If active patient exists, load ONLY that patient's isolated context file
        if chat_ctx.patient_id:
            try:
                # Load the patient-specific file (isolated history)
                isolated_ctx = await chat_context_accessor.read(conversation_id, chat_ctx.patient_id)
                if isolated_ctx and isolated_ctx.chat_history.messages:
                    # Replace with isolated chat history
                    chat_ctx.chat_history = isolated_ctx.chat_history
                    logger.info(
                        f"Loaded isolated history for {chat_ctx.patient_id} ({len(isolated_ctx.chat_history.messages)} messages)")
                else:
                    logger.info(f"No existing history for {chat_ctx.patient_id}, starting fresh")
            except Exception as e:
                logger.debug(f"Could not load isolated context for {chat_ctx.patient_id}: {e}")

        # STEP 4: Continue with normal group chat processing
        agents = self.all_agents
        if len(chat_ctx.chat_history.messages) == 0:
            # new conversation. Let's see which agents are available.
            async def is_part_of_conversation(agent):
                context = await self.get_bot_context(turn_context.activity.conversation.id, agent["name"], turn_context)
                typing_activity = Activity(
                    type=ActivityTypes.typing,
                    relates_to=turn_context.activity.relates_to,
                )
                typing_activity.apply_conversation_reference(
                    turn_context.activity.get_conversation_reference()
                )
                context.activity = typing_activity
                try:
                    await context.send_activity(typing_activity)
                    return True
                except Exception as e:
                    logger.info(f"Failed to send typing activity to {agent['name']}: {e}")
                    # This happens if the agent is not part of the group chat.
                    # Remove the agent from the list of available agents
                    return False

            part_of_conversation = await asyncio.gather(*(is_part_of_conversation(agent) for agent in self.all_agents))
            agents = [agent for agent, should_include in zip(self.all_agents, part_of_conversation) if should_include]

        (chat, chat_ctx) = create_group_chat(self.app_context, chat_ctx, participants=agents)

        # Add user message with patient context
        user_message_with_context = self._append_pc_ctx(f"{self.name}: {raw_user_text}", chat_ctx)
        chat_ctx.chat_history.add_user_message(user_message_with_context)

        chat.is_complete = False
        await self.process_chat(chat, chat_ctx, turn_context)

        # Save chat context
        try:
            await chat_context_accessor.write(chat_ctx)
            logger.info(f"Saved context for conversation: {conversation_id} | Patient: {chat_ctx.patient_id}")
        except Exception as e:
            logger.exception("Failed to save chat context.")

    async def on_error(self, context: TurnContext, error: Exception):
        # This error is raised as Exception, so we can only use the message to handle the error.
        if str(error) == "Unable to proceed while another agent is active.":
            await context.send_activity("Please wait for the current agent to finish.")
        elif isinstance(error, NotAuthorizedError):
            logger.warning(error)
            await context.send_activity("You are not authorized to access this agent.")
        else:
            # default exception handling
            logger.exception(f"Agent {self.name} encountered an error")
            await context.send_activity(f"Orchestrator is working on solving your problems, please retype your request")

    async def process_chat(
        self, chat: AgentGroupChat, chat_ctx: ChatContext, turn_context: TurnContext
    ):
        # If the mentioned agent is a facilitator, proceed with group chat.
        # Otherwise, proceed with standalone chat using the mentioned agent.
        agent_config = next(agent_config for agent_config in self.all_agents if agent_config["name"] == self.name)
        mentioned_agent = None if agent_config.get("facilitator", False) \
            else next(agent for agent in chat.agents if agent.name == self.name)

        async for response in chat.invoke(agent=mentioned_agent):
            context = await self.get_bot_context(
                turn_context.activity.conversation.id, response.name, turn_context
            )
            if response.content.strip() == "":
                continue

            # Add patient context to response
            response_with_context = self._append_pc_ctx(response.content, chat_ctx)

            # Update response properly with ChatMessageContent v2 format
            if hasattr(response, 'items') and response.items:
                response.items[0].text = response_with_context
            else:
                # If no items structure, recreate with proper format
                response = ChatMessageContent(
                    role=response.role,
                    items=[TextContent(text=response_with_context)],
                    name=getattr(response, 'name', None)
                )

            msgText = self._append_links_to_msg(response.content, chat_ctx)
            msgText = await self.generate_sas_for_blob_urls(msgText, chat_ctx)

            activity = MessageFactory.text(msgText)
            activity.apply_conversation_reference(
                turn_context.activity.get_conversation_reference()
            )
            context.activity = activity

            await context.send_activity(activity)

            if chat.is_complete:
                break

    def _append_links_to_msg(self, msgText: str, chat_ctx: ChatContext) -> str:
        # Add patient data links to response
        try:
            # Handle both main branch format (direct access) and patient context format (getattr)
            image_urls = getattr(chat_ctx, 'display_image_urls', [])
            clinical_trial_urls = chat_ctx.display_clinical_trials

            # Display loaded images
            if image_urls:
                msgText += "<h2>Patient Images</h2>"
                for url in image_urls:
                    filename = url.split("/")[-1]
                    msgText += f"<img src='{url}' alt='{filename}' height='300px'/>"

            # Display clinical trials
            if clinical_trial_urls:
                msgText += "<h2>Clinical trials</h2>"
                for url in clinical_trial_urls:
                    trial = url.split("/")[-1]
                    msgText += f"<li><a href='{url}'>{trial}</a></li>"

            return msgText
        finally:
            # Handle both formats for cleanup
            if hasattr(chat_ctx, 'display_image_urls'):
                chat_ctx.display_image_urls = []
            chat_ctx.display_clinical_trials = []

    async def generate_sas_for_blob_urls(self, msgText: str, chat_ctx: ChatContext) -> str:
        try:
            for blob_url in chat_ctx.display_blob_urls:
                blob_sas_url = await self.data_access.blob_sas_delegate.get_blob_sas_url(blob_url)
                msgText = msgText.replace(blob_url, blob_sas_url)

            return msgText
        finally:
            chat_ctx.display_blob_urls = []

    def _get_system_patient_context_json(self, chat_ctx: ChatContext) -> str | None:
        """Extract the JSON payload from the current PATIENT_CONTEXT_JSON system message."""
        for msg in chat_ctx.chat_history.messages:
            if msg.role == AuthorRole.SYSTEM:
                # Handle both string content and itemized content
                content = msg.content
                if isinstance(content, str):
                    text = content
                else:
                    # Try to extract from items if content is structured
                    items = getattr(msg, "items", None) or getattr(content, "items", None)
                    if items:
                        parts = []
                        for item in items:
                            item_text = getattr(item, "text", None) or getattr(item, "content", None)
                            if item_text:
                                parts.append(str(item_text))
                        text = "".join(parts) if parts else str(content) if content else ""
                    else:
                        text = str(content) if content else ""

                if text and text.startswith(PATIENT_CONTEXT_PREFIX):
                    # Extract JSON after "PATIENT_CONTEXT_JSON:"
                    json_part = text[len(PATIENT_CONTEXT_PREFIX):].strip()
                    if json_part.startswith(":"):
                        json_part = json_part[1:].strip()
                    return json_part if json_part else None
        return None

    def _append_pc_ctx(self, base: str, chat_ctx: ChatContext) -> str:
        """Append patient context information to the message for display."""

        # Avoid double-tagging
        if "\nPC_CTX" in base or "\n*PT_CTX:*" in base:
            return base

        # Get the actual injected system patient context JSON
        json_payload = self._get_system_patient_context_json(chat_ctx)

        if not json_payload:
            return base

        # Format the JSON payload into a simple, readable Markdown string
        try:
            obj = json.loads(json_payload)

            lines = ["\n\n---", "\n*PT_CTX:*"]
            if obj.get("patient_id"):
                lines.append(f"- **Patient ID:** `{obj['patient_id']}`")
            if obj.get("conversation_id"):
                lines.append(f"- **Conversation ID:** `{obj['conversation_id']}`")

            if obj.get("all_patient_ids"):
                active_id = obj.get("patient_id")
                ids_str = ", ".join(f"`{p}`{' (active)' if p == active_id else ''}" for p in obj["all_patient_ids"])
                lines.append(f"- **Session Patients:** {ids_str}")

            if not obj.get("patient_id"):
                lines.append("- *No active patient.*")

            # Only add the block if there's something to show besides the header
            if len(lines) > 2:
                formatted_text = "\n".join(lines)
                logger.debug(f"Appended patient context to message | Patient: {obj.get('patient_id')}")
                return f"{base}{formatted_text}"
            else:
                return base

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse patient context JSON: {e}")
            # Fallback to raw if JSON is malformed, but keep it simple
            return f"{base}\n\n---\n*PT_CTX (raw):* `{json_payload}`"

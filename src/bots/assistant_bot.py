# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import asyncio
import json
import logging
import os
import json

from botbuilder.core import MessageFactory, TurnContext
from botbuilder.core.teams import TeamsActivityHandler
from botbuilder.integration.aiohttp import CloudAdapter
from botbuilder.schema import Activity, ActivityTypes
from semantic_kernel.agents import AgentGroupChat


from semantic_kernel.contents import AuthorRole
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

        analyzer = PatientContextAnalyzer(token_provider=app_context.cognitive_services_token_provider)
        self.patient_context_service = PatientContextService(analyzer=analyzer)

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

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        conversation_id = turn_context.activity.conversation.id
        chat_context_accessor = self.data_access.chat_context_accessor
        chat_artifact_accessor = self.data_access.chat_artifact_accessor

        chat_ctx = await chat_context_accessor.read(conversation_id)

        # Extract raw user text (without bot mention) once
        raw_user_text = turn_context.remove_recipient_mention(turn_context.activity).strip()

        # Full conversation clear (existing behavior)
        if raw_user_text.endswith("clear"):
            chat_ctx.chat_history.add_user_message(raw_user_text)
            await chat_context_accessor.archive(chat_ctx)
            await chat_artifact_accessor.archive(conversation_id)
            await turn_context.send_activity("Conversation cleared!")
            return

        # Decide & apply patient context BEFORE building group chat
        logger.info(f"Processing patient context for conversation: {conversation_id}")

        decision, timing = await self.patient_context_service.decide_and_apply(raw_user_text, chat_ctx)

        logger.info(f"Patient context decision: {decision} | Patient: {chat_ctx.patient_id} | Timing: {timing}")

        agents = self.all_agents
        if len(chat_ctx.chat_history.messages) == 0:
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
                    logger.debug(f"Failed to send typing activity to {agent['name']}: {e}")
                    return False

            part_of_conversation = await asyncio.gather(*(is_part_of_conversation(agent) for agent in self.all_agents))
            agents = [agent for agent, include in zip(self.all_agents, part_of_conversation) if include]

        (chat, chat_ctx) = create_group_chat(self.app_context, chat_ctx, participants=agents)

        # Add user message after context decision (no extra tagging here)
        user_with_ctx = self._append_pc_ctx(f"{self.name}: {raw_user_text}", chat_ctx)
        chat_ctx.chat_history.add_user_message(user_with_ctx)

        chat.is_complete = False
        await self.process_chat(chat, chat_ctx, turn_context)

        try:
            await chat_context_accessor.write(chat_ctx)
        except:
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

            # msgText = self._append_links_to_msg(response.content, chat_ctx)

            # Add this code right before the existing `response.content = self._append_pc_ctx(response.content, chat_ctx)` line:
            # Record active agent in PATIENT_CONTEXT_JSON
            # try:
            #    self._set_system_pc_ctx_agent(chat_ctx, "active", response.name)
            # except Exception as e:
            #    logger.info(f"Failed to set active agent in PC_CTX: {e}")

            # Attach current patient context snapshot to assistant output+
            response.content = self._append_pc_ctx(response.content, chat_ctx)
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
            image_urls = chat_ctx.display_image_urls
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

            summary_raw = obj.get("chat_summary", "")
            if summary_raw and summary_raw.strip():
                # Check if it's the default "no specific information" message
                if "No specific information was discussed" in summary_raw:
                    lines.append(f"- **Summary:** *Building patient context...*")
                else:
                    # Clean up summary for display
                    summary = summary_raw.replace('\n', ' ').strip()
                    lines.append(f"- **Summary:** *{summary}*")
            else:
                lines.append(f"- **Summary:** *Building patient context...*")

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

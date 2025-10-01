# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import asyncio
import logging
import os
import json
from datetime import datetime, timezone

from botbuilder.core import MessageFactory, TurnContext
from botbuilder.core.teams import TeamsActivityHandler
from botbuilder.integration.aiohttp import CloudAdapter
from botbuilder.schema import Activity, ActivityTypes
from semantic_kernel.agents import AgentGroupChat
from semantic_kernel.contents import ChatMessageContent, TextContent, AuthorRole

from data_models.app_context import AppContext
from data_models.chat_context import ChatContext

from group_chat import create_group_chat
from services.patient_context_service import PatientContextService, PATIENT_CONTEXT_PREFIX
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
        self.patient_context_service = PatientContextService(
            analyzer=analyzer,
            registry_accessor=app_context.data_access.patient_context_registry_accessor,
            context_accessor=app_context.data_access.chat_context_accessor
        )

    async def get_bot_context(self, conversation_id: str, bot_name: str, turn_context: TurnContext):
        if conversation_id not in self.turn_contexts:
            self.turn_contexts[conversation_id] = {}
        if bot_name not in self.turn_contexts[conversation_id]:
            context = await self.create_turn_context(bot_name, turn_context)
            self.turn_contexts[conversation_id][bot_name] = context
        return self.turn_contexts[conversation_id][bot_name]

    async def create_turn_context(self, bot_name, turn_context):
        app_id = next(agent["bot_id"] for agent in self.all_agents if agent["name"] == bot_name)
        adapter = self.adapters[bot_name]
        claims_identity = adapter.create_claims_identity(app_id)
        connector_factory = adapter.bot_framework_authentication.create_connector_factory(claims_identity)
        connector_client = await connector_factory.create(turn_context.activity.service_url, "https://api.botframework.com")
        user_token_client = await adapter.bot_framework_authentication.create_user_token_client(claims_identity)

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
        content_lower = content.lower().strip()
        if content_lower in ["clear", "clear patient", "clear context", "clear patient context"]:
            logger.info(f"Processing clear command for conversation: {conversation_id}")
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
            archive_folder = f"archive/{timestamp}"
            try:
                await self.data_access.chat_context_accessor.archive_to_folder(conversation_id, None, archive_folder)
                try:
                    patient_registry, _ = await self.patient_context_service.registry_accessor.read_registry(conversation_id)
                    if patient_registry:
                        for pid in patient_registry.keys():
                            await self.data_access.chat_context_accessor.archive_to_folder(conversation_id, pid, archive_folder)
                except Exception:
                    if getattr(chat_ctx, "patient_contexts", None):
                        for pid in chat_ctx.patient_contexts.keys():
                            await self.data_access.chat_context_accessor.archive_to_folder(conversation_id, pid, archive_folder)
                await self.patient_context_service.registry_accessor.archive_registry(conversation_id)
            except Exception as e:
                logger.warning(f"Clear archival issues: {e}")
            finally:
                chat_ctx.patient_context = None
                if hasattr(chat_ctx, "patient_contexts"):
                    chat_ctx.patient_contexts.clear()
                chat_ctx.chat_history.clear()
                chat_ctx.patient_id = None
                await self.data_access.chat_context_accessor.write(chat_ctx)
            return True
        return False

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        conversation_id = turn_context.activity.conversation.id
        chat_context_accessor = self.data_access.chat_context_accessor
        chat_artifact_accessor = self.data_access.chat_artifact_accessor

        raw_user_text = turn_context.remove_recipient_mention(turn_context.activity).strip()

        try:
            chat_ctx = await chat_context_accessor.read(conversation_id, None)
        except Exception:
            chat_ctx = ChatContext(conversation_id)

        if await self._handle_clear_command(raw_user_text, chat_ctx, conversation_id):
            await chat_artifact_accessor.archive(conversation_id)
            await turn_context.send_activity("Conversation cleared!")
            return

        decision, timing = await self.patient_context_service.decide_and_apply(raw_user_text, chat_ctx)
        if decision == "NEEDS_PATIENT_ID":
            await turn_context.send_activity(
                "I need a patient ID like 'patient_4' (e.g., '@Orchestrator start tumor board review for patient_4')."
            )
            return

        if chat_ctx.patient_id:
            try:
                isolated = await chat_context_accessor.read(conversation_id, chat_ctx.patient_id)
                if isolated and isolated.chat_history.messages:
                    chat_ctx.chat_history = isolated.chat_history
            except Exception:
                pass

        # Inject fresh ephemeral PATIENT_CONTEXT_JSON snapshot
        filtered = []
        for m in chat_ctx.chat_history.messages:
            if not (m.role == AuthorRole.SYSTEM and hasattr(m, "items") and m.items
                    and getattr(m.items[0], "text", "").startswith(PATIENT_CONTEXT_PREFIX)):
                filtered.append(m)
        chat_ctx.chat_history.messages = filtered
        snapshot = {
            "conversation_id": chat_ctx.conversation_id,
            "patient_id": chat_ctx.patient_id,
            "all_patient_ids": sorted(getattr(chat_ctx, "patient_contexts", {}).keys()),
            "generated_at": datetime.utcnow().isoformat() + "Z"
        }
        line = f"{PATIENT_CONTEXT_PREFIX}: {json.dumps(snapshot, separators=(',', ':'))}"
        sys_msg = ChatMessageContent(role=AuthorRole.SYSTEM, items=[TextContent(text=line)])
        chat_ctx.chat_history.messages.insert(0, sys_msg)

        agents = self.all_agents
        if len(chat_ctx.chat_history.messages) == 1:  # only the snapshot present
            async def is_part(agent):
                context = await self.get_bot_context(conversation_id, agent["name"], turn_context)
                typing = Activity(type=ActivityTypes.typing, relates_to=turn_context.activity.relates_to)
                typing.apply_conversation_reference(turn_context.activity.get_conversation_reference())
                context.activity = typing
                try:
                    await context.send_activity(typing)
                    return True
                except Exception:
                    return False

            flags = await asyncio.gather(*(is_part(a) for a in self.all_agents))
            agents = [a for a, ok in zip(self.all_agents, flags) if ok]

        (chat, chat_ctx) = create_group_chat(self.app_context, chat_ctx, participants=agents)

        # Add raw user message
        chat_ctx.chat_history.add_user_message(raw_user_text)

        chat.is_complete = False
        await self.process_chat(chat, chat_ctx, turn_context)

        try:
            await chat_context_accessor.write(chat_ctx)
        except Exception:
            logger.exception("Failed to save chat context.")

    async def on_error(self, context: TurnContext, error: Exception):
        from errors import NotAuthorizedError
        if str(error) == "Unable to proceed while another agent is active.":
            await context.send_activity("Please wait for the current agent to finish.")
        elif isinstance(error, NotAuthorizedError):
            await context.send_activity("You are not authorized to access this agent.")
        else:
            await context.send_activity("Orchestrator encountered an error. Please retry your request.")

    async def process_chat(self, chat: AgentGroupChat, chat_ctx: ChatContext, turn_context: TurnContext):
        agent_cfg = next(cfg for cfg in self.all_agents if cfg["name"] == self.name)
        mentioned_agent = None if agent_cfg.get("facilitator", False) else next(
            a for a in chat.agents if a.name == self.name)

        async for response in chat.invoke(agent=mentioned_agent):
            if not response.content.strip():
                continue

            active_pid = chat_ctx.patient_id
            all_pids = sorted(getattr(chat_ctx, "patient_contexts", {}).keys())
            final_content = response.content

            # Option 3 guard + added Session ID line
            if all_pids and "PT_CTX:" not in response.content:
                roster = ", ".join(f"`{p}`{' (active)' if p == active_pid else ''}" for p in all_pids)
                pt_ctx_block = "\n\n---\n*PT_CTX:*\n"
                pt_ctx_block += f"- **Session ID:** `{chat_ctx.conversation_id}`\n"
                pt_ctx_block += f"- **Patient ID:** `{active_pid}`\n" if active_pid else "- *No active patient.*\n"
                pt_ctx_block += f"- **Session Patients:** {roster}"
                final_content = f"{response.content}{pt_ctx_block}"

            if hasattr(response, "items") and response.items:
                response.items[0].text = final_content
            else:
                response = ChatMessageContent(
                    role=response.role,
                    items=[TextContent(text=final_content)],
                    name=getattr(response, "name", None)
                )

            msgText = self._append_links_to_msg(response.content, chat_ctx)
            msgText = await self.generate_sas_for_blob_urls(msgText, chat_ctx)

            context = await self.get_bot_context(turn_context.activity.conversation.id, response.name, turn_context)
            activity = MessageFactory.text(msgText)
            activity.apply_conversation_reference(turn_context.activity.get_conversation_reference())
            context.activity = activity
            await context.send_activity(activity)

            if chat.is_complete:
                break

    def _append_links_to_msg(self, msgText: str, chat_ctx: ChatContext) -> str:
        try:
            imgs = getattr(chat_ctx, "display_image_urls", [])
            trials = chat_ctx.display_clinical_trials
            if imgs:
                msgText += "<h2>Patient Images</h2>"
                for url in imgs:
                    fname = url.split("/")[-1]
                    msgText += f"<img src='{url}' alt='{fname}' height='300px'/>"
            if trials:
                msgText += "<h2>Clinical trials</h2>"
                for url in trials:
                    trial = url.split("/")[-1]
                    msgText += f"<li><a href='{url}'>{trial}</a></li>"
            return msgText
        finally:
            if hasattr(chat_ctx, "display_image_urls"):
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

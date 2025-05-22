# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import asyncio
import logging
import os

from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import (MemoryQueryEvent, ModelClientStreamingChunkEvent, ThoughtEvent,
                                        ToolCallExecutionEvent, ToolCallRequestEvent, UserInputRequestedEvent)
from autogen_agentchat.teams import MagenticOneGroupChat
from autogen_core import CancellationToken
from botbuilder.core import ActivityHandler, MessageFactory, TurnContext
from botbuilder.integration.aiohttp import CloudAdapter

from data_models.app_context import AppContext
from data_models.chat_context import ChatContext
from group_chat import create_group_chat
from magentic_chat import create_magentic_chat

logger = logging.getLogger(__name__)


class MagenticBot(ActivityHandler):
    """
    Provides a bot that can be used to interact with the MagenticOneOrchestrator agent.
    This is experimental, and uses the storage as the underlying mechanism to coordinate task and user input.
    When conversation starts, it creates a new blob in the storage to indicate that the conversation is in progress.
    When the chat needs input, it waits for the user to provide input in the blob.
    Better and more rubust mechanisms can be used in the future if magentic chat is found to be useful.
    """

    def __init__(
        self,
        agent: dict,
        adapters: dict[str, CloudAdapter],
        turn_contexts: dict[str, dict[str, TurnContext]],
        app_context: AppContext
    ):
        self.app_context = app_context
        self.all_agents = app_context.all_agent_configs
        self.adapters = adapters
        self.name = agent["name"]
        self.adapters[self.name].on_turn_error = self.on_error  # add error handling
        self.turn_contexts = turn_contexts
        self.data_access = app_context.data_access
        self.container_client = self.data_access.chat_context_accessor.container_client
        self.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.include_monologue = True

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        conversation_id = turn_context.activity.conversation.id
        chat_context_accessor = self.data_access.chat_context_accessor
        chat_artifact_accessor = self.data_access.chat_artifact_accessor

        # Load chat context
        chat_ctx = await chat_context_accessor.read(conversation_id)

        # Delete thread if user asks
        if turn_context.activity.text.endswith("monologue"):
            if self.include_monologue:
                await turn_context.send_activity("Monologue mode disabled.")
                self.include_monologue = False
            else:
                await turn_context.send_activity("Monologue mode enabled.")
                self.include_monologue = True
            return

        if turn_context.activity.text.endswith("clear"):
            # Add clear message to chat history
            chat_ctx.chat_history.add_user_message(turn_context.activity.text.strip())
            await chat_context_accessor.archive(chat_ctx)
            await chat_artifact_accessor.archive(conversation_id)
            blob_path = f"{turn_context.activity.conversation.id}/user_message.txt"
            blob_client = self.container_client.get_blob_client(blob_path)
            try:
                await blob_client.delete_blob()
            except:
                logger.exception("Failed to delete user message blob.")

            blob_path_conversation = f"{turn_context.activity.conversation.id}/conversation_in_progress.txt"

            blob_client = self.container_client.get_blob_client(blob_path_conversation)
            try:
                await blob_client.delete_blob()
            except:
                logger.exception("Failed to delete conversation in progress blob.")

            await turn_context.send_activity("Conversation cleared!")
            return

        (chat, chat_ctx) = create_group_chat(self.app_context, chat_ctx)
        logger.info(f"Created chat for conversation {conversation_id}")

        blob_path_conversation = f"{turn_context.activity.conversation.id}/conversation_in_progress.txt"
        blob_client = self.container_client.get_blob_client(blob_path_conversation)

        text = turn_context.remove_recipient_mention(turn_context.activity).strip()

        if await blob_client.exists():
            logger.info("Conversation in progress, assuming reply.")
            chat_ctx.chat_history.add_user_message(text)
            await self.user_message_provided(text, turn_context)
        else:
            logger.info(f"Creating Magentic chat for conversation {conversation_id}")
            magentic_chat = create_magentic_chat(
                chat, self.app_context, self.create_input_func_callback(turn_context, chat_ctx))

            await self.process_magentic_chat(magentic_chat, text, turn_context, chat_ctx)

        # Save chat context
        try:
            await chat_context_accessor.write(chat_ctx)
        except:
            logger.exception("Failed to save chat context.")

    async def on_error(self, context: TurnContext, error: Exception):
        # This error is raised as Exception, so we can only use the message to handle the error.
        if str(error) == "Unable to proceed while another agent is active.":
            await context.send_activity("Please wait for the current agent to finish.")
        else:
            # default exception handling
            logger.exception(f"Agent {self.name} encountered an error")
            await context.send_activity(f"Orchestrator is working on solving your problems, please retype your request")

    async def user_message_provided(self, message: str, turn_context: TurnContext):
        blob_path = f"{turn_context.activity.conversation.id}/user_message.txt"
        blob_client = self.container_client.get_blob_client(blob_path)
        await blob_client.upload_blob(message, overwrite=True)

    def create_input_func_callback(self, turn_context: TurnContext, chat_ctx: ChatContext):
        async def user_input_func(prompt: str, cancellation_token: CancellationToken):
            logger.info(f"User input requested: {prompt}")
            await turn_context.send_activity("**User**: " + chat_ctx.chat_history.messages[-1].content)

            blob_path_conversation = f"{turn_context.activity.conversation.id}/conversation_in_progress.txt"
            conversation_blob = self.container_client.get_blob_client(blob_path_conversation)
            await conversation_blob.upload_blob("conversation in progress", overwrite=True)

            blob_path = f"{turn_context.activity.conversation.id}/user_message.txt"
            user_message_blob = self.container_client.get_blob_client(blob_path)
            while not (await user_message_blob.exists()):
                await asyncio.sleep(0.5)
                logger.info("Waiting for user input...")

            blob = await user_message_blob.download_blob()
            blob_str = await blob.readall()

            await conversation_blob.delete_blob()
            await user_message_blob.delete_blob()

            return blob_str.decode("utf-8")

        return user_input_func

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

    async def get_bot_context(
        self, conversation_id: str, bot_name: str, turn_context: TurnContext
    ):
        if conversation_id not in self.turn_contexts:
            self.turn_contexts[conversation_id] = {}

        if bot_name not in self.turn_contexts[conversation_id]:
            context = await self.create_turn_context(bot_name, turn_context)

            self.turn_contexts[conversation_id][bot_name] = context

        return self.turn_contexts[conversation_id][bot_name]

    async def process_magentic_chat(self, magentic_chat: MagenticOneGroupChat, text: str, turn_context: TurnContext, chat_ctx: ChatContext):
        last_result = None
        stream = magentic_chat.run_stream(task=text, cancellation_token=CancellationToken())
        logger.info(f"Processing Magentic chat for conversation {turn_context.activity.conversation.id}")
        async for message in stream:
            logger.info(f"received message: {message}")
            if isinstance(message, (ToolCallRequestEvent,
                                    ToolCallExecutionEvent, MemoryQueryEvent, UserInputRequestedEvent, ModelClientStreamingChunkEvent, ThoughtEvent)):
                continue

            elif isinstance(message, UserInputRequestedEvent):
                logger.info("user input requested")
                continue
            elif isinstance(message, TaskResult):
                logger.info("Task result")
                last_result = message
            else:
                agent_name = message.source
                if agent_name == "user":
                    logger.info("User agent message")
                    continue
                if agent_name == "MagenticOneOrchestrator":
                    agent_name = self.name
                    logger.info("MagenticOneOrchestrator agent name")
                context = await self.get_bot_context(
                    turn_context.activity.conversation.id, agent_name, turn_context
                )
                if message.content.strip() == "":
                    continue

                chat_ctx.chat_history.add_assistant_message(message.content, name=agent_name)

                activity = MessageFactory.text(message.content)
                activity.apply_conversation_reference(
                    turn_context.activity.get_conversation_reference()
                )
                context.activity = activity
                if self.include_monologue:
                    await context.send_activity(activity)
            if last_result:
                if not self.include_monologue:
                    await turn_context.send_activity(
                        MessageFactory.text(chat_ctx.chat_history.messages[-1].content)
                    )

                await turn_context.send_activity(
                    MessageFactory.text(last_result.stop_reason)
                )

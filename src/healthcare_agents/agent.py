# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging
import os
from collections.abc import AsyncIterable
from typing import ClassVar, override

from azure.keyvault.secrets.aio import SecretClient
from semantic_kernel.agents.agent import Agent
from semantic_kernel.agents.channels.agent_channel import AgentChannel
from semantic_kernel.contents import AuthorRole, ChatMessageContent
from semantic_kernel.exceptions import AgentInvokeException

from data_models.app_context import AppContext
from data_models.chat_context import ChatContext
from healthcare_agents.client import HealthcareAgentServiceClient
from healthcare_agents.config import config

logger = logging.getLogger(__name__)


class HealthcareAgentChannel(AgentChannel):
    """Healthcare Agent Service - Direct Line channel."""

    def __init__(self):
        super().__init__()
        self.history: list[ChatMessageContent] = []
        logger.debug("HealthcareAgentChannel initialized.")

    @override
    async def receive(self, history: list[ChatMessageContent]) -> None:
        for message in history:
            logger.debug("[history] Received message: %s", message.content)
            if message.content.strip() != "":
                self.history.append(message)

    @override
    async def invoke(self, agent: "HealthcareAgent") -> AsyncIterable[tuple[bool, ChatMessageContent]]:
        logger.debug("Invoking agent: %s, with user input: %s", agent.name, self.history[-1].content)
        user_input = self.history[-1].content
        user_message = ChatMessageContent(role=AuthorRole.USER,
                                          content=user_input)
        self.history.append(user_message)

        if agent.client:
            attachments: list[dict] = await agent.get_attachments()
            response_dict = await agent.client.process(user_message.content, attachments)
            response_message = ChatMessageContent(
                role=AuthorRole.ASSISTANT,
                name=agent.name,
                content=response_dict.get("text", ""))
            self.history.append(response_message)
            yield True, response_message
        else:
            yield True, user_message

    @override
    async def invoke_stream(self, agent: "HealthcareAgent", history: "list[ChatMessageContent]"):
        raise NotImplementedError("invoke_stream is not implemented yet.")

    @override
    async def get_history(self) -> AsyncIterable[ChatMessageContent]:
        logger.debug("Getting history from HealthcareAgentChannel.")
        for message in reversed(self.history):
            yield message

    @override
    async def reset(self) -> None:
        logger.debug("Resetting HealthcareAgentChannel.")
        self.history.clear()


class HealthcareAgent(Agent):
    """Healthcare Agent class for interacting with Healthcare Agent Service."""

    channel_type: ClassVar[type[AgentChannel]] = HealthcareAgentChannel

    def __init__(self,
                 name: str = None,
                 chat_ctx: ChatContext = None,
                 app_ctx: AppContext = None,
                 ):
        super().__init__(name=name)
        self.name = name
        self._chat_ctx = chat_ctx
        self._data_access = app_ctx.data_access
        self._client: HealthcareAgentServiceClient = None

        if not name:
            raise ValueError("Agent name is required.")
        if not chat_ctx:
            raise ValueError("Chat context is required.")
        if not app_ctx:
            raise ValueError("Application context is required.")

        # Initialize the HealthcareAgentServiceClient
        logger.debug("Initializing HealthcareAgentServiceClient.")
        self._client: HealthcareAgentServiceClient = HealthcareAgentServiceClient(
            agent_name=name,
            chat_ctx=chat_ctx,
            url=config.directline_url,
            keyvault_client=SecretClient(
                vault_url=os.getenv("KEYVAULT_ENDPOINT"),
                credential=app_ctx.credential,
            ),
            directline_secret_key=config.keyvault_secret_key_name.format(name=name),
            max_retries=config.max_retries,
            retry_delay=config.retry_delay,
            timeout=config.timeout
        )
        # Restore conversation ID if it exists
        if name in self._chat_ctx.healthcare_agents:
            self._client.set_conversation_id(
                self._chat_ctx.healthcare_agents[name].get("conversation_id", None))
        logger.debug(f"HealthcareAgent initialized: {name}")

    @property
    def client(self):
        return self._client

    async def create_channel(self) -> AgentChannel:
        logger.debug("Creating HealthcareAgentChannel.")
        return HealthcareAgentChannel()

    @override
    async def get_response(self, message: str) -> ChatMessageContent:
        logger.debug("Getting response for message: %s", message)
        attachments = await self.get_attachments()
        response_dict = await self.client.process(message, attachments)
        return ChatMessageContent(
            role=AuthorRole.ASSISTANT,
            name=self.name,
            content=response_dict.get("text", "")
        )

    @override
    async def invoke(self, *args, **kwargs) -> AsyncIterable[ChatMessageContent]:
        """Invoke the agent and yield a response."""
        message = kwargs.get("message")
        logger.debug("Invoking HealthcareAgent with message: %s", message)
        if not message:
            raise AgentInvokeException("Message is required to invoke the agent.")
        response = await self.get_response(message)
        yield response

    @override
    async def invoke_stream(self, *args, **kwargs) -> AsyncIterable[ChatMessageContent]:
        """Invoke the agent as a stream."""
        raise NotImplementedError("invoke_stream is not implemented.")

    async def get_attachments(self) -> list[dict]:
        """Get the attachments from the conversation history."""
        attachments = []
        for data in self._chat_ctx.patient_data:
            if data['type'] in ['x-ray image']:
                filename = data['filename']
                blob_sas_url = await self._data_access.blob_sas_delegate.get_blob_sas_url(data['url'])
                attachments.append({
                    'name': filename,
                    'contentType': ("image/png" if filename.endswith('.png')
                                    else "image/jpeg" if filename.endswith('.jpg')
                                    else "application/octet-stream"),
                    'contentUrl': blob_sas_url,
                })
        return attachments

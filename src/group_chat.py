# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import importlib
import logging
import os
from typing import Any, Awaitable, Callable, Tuple, override

from pydantic import BaseModel
from semantic_kernel import Kernel
from semantic_kernel.agents import AgentGroupChat, ChatCompletionAgent
from semantic_kernel.agents.channels.chat_history_channel import ChatHistoryChannel
from semantic_kernel.agents.strategies.selection.kernel_function_selection_strategy import (
    KernelFunctionSelectionStrategy,
)
from semantic_kernel.agents.strategies.termination.kernel_function_termination_strategy import (
    KernelFunctionTerminationStrategy,
)
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import (
    AzureChatPromptExecutionSettings,
)
from semantic_kernel.connectors.ai.open_ai.services.azure_chat_completion import (
    AzureChatCompletion,
)
from semantic_kernel.connectors.openapi_plugin import OpenAPIFunctionExecutionParameters
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.contents.history_reducer.chat_history_truncation_reducer import (
    ChatHistoryTruncationReducer,
)
from semantic_kernel.functions.kernel_function_from_prompt import (
    KernelFunctionFromPrompt,
)
from semantic_kernel.kernel import Kernel, KernelArguments
from semantic_kernel.contents import ChatMessageContent

from data_models.app_context import AppContext
from data_models.chat_context import ChatContext
from data_models.plugin_configuration import PluginConfiguration
from healthcare_agents import HealthcareAgent
from healthcare_agents import config as healthcare_agent_config
from utils.model_utils import model_supports_temperature

DEFAULT_MODEL_TEMP = 0
DEFAULT_TOOL_TYPE = "function"

logger = logging.getLogger(__name__)


class CustomHistoryChannel(ChatHistoryChannel):
    @override
    async def receive(
        self,
        history: list[ChatMessageContent],
    ) -> None:
        await super().receive(history)
        for message in history[:-1]:
            await self.thread.on_new_message(message)


class CustomChatCompletionAgent(ChatCompletionAgent):
    """Custom ChatCompletionAgent to override the create_channel method."""

    @override
    async def create_channel(
        self, chat_history: ChatHistory | None = None, thread_id: str | None = None
    ) -> CustomHistoryChannel:
        from semantic_kernel.agents.chat_completion.chat_completion_agent import (
            ChatHistoryAgentThread,
        )

        CustomHistoryChannel.model_rebuild()
        thread = ChatHistoryAgentThread(chat_history=chat_history, thread_id=thread_id)

        if thread.id is None:
            await thread.create()

        messages = [message async for message in thread.get_messages()]
        return CustomHistoryChannel(messages=messages, thread=thread)


class ChatRule(BaseModel):
    """Structured output model for group chat selection and termination decisions."""
    verdict: str
    reasoning: str


def create_auth_callback(chat_ctx: ChatContext) -> Callable[..., Awaitable[Any]]:
    """Creates an authentication callback for OpenAPI tool execution."""
    async def auth_callback():
        return {"conversation-id": chat_ctx.conversation_id}
    return auth_callback


def create_group_chat(
    app_ctx: AppContext,
    chat_ctx: ChatContext,
    participants: list[dict] = None,
) -> Tuple[AgentGroupChat, ChatContext]:
    """
    Create a multi-agent group chat.

    Args:
        app_ctx: Application context containing shared resources
        chat_ctx: Chat context for conversation state
        participants: Optional list of participant configurations

    Returns:
        Tuple of AgentGroupChat instance and updated ChatContext
    """
    participant_configs = participants or app_ctx.all_agent_configs
    participant_names = [cfg.get("name") for cfg in participant_configs]
    logger.info("Creating group chat with participants: %s", participant_names)

    # Remove magentic agent from the list of agents
    all_agents_config = [
        agent for agent in participant_configs if agent.get("name") != "magentic"
    ]

    def _create_kernel_with_chat_completion() -> Kernel:
        """Create a kernel instance with Azure OpenAI chat completion service."""
        kernel = Kernel()
        kernel.add_service(
            AzureChatCompletion(
                service_id="default",
                deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
                api_version="2025-04-01-preview",
                ad_token_provider=app_ctx.cognitive_services_token_provider,
            )
        )
        return kernel

    def _create_agent(agent_config: dict):
        """Create an agent instance based on configuration."""
        agent_kernel = _create_kernel_with_chat_completion()
        plugin_config = PluginConfiguration(
            kernel=agent_kernel,
            agent_config=agent_config,
            data_access=app_ctx.data_access,
            chat_ctx=chat_ctx,
            azureml_token_provider=app_ctx.azureml_token_provider,
        )
        is_healthcare_agent = (
            healthcare_agent_config.yaml_key in agent_config
            and bool(agent_config[healthcare_agent_config.yaml_key])
        )

        for tool in agent_config.get("tools", []):
            tool_name = tool.get("name")
            tool_type = tool.get("type", DEFAULT_TOOL_TYPE)

            if tool_type == "function":
                scenario = os.environ.get("SCENARIO")
                tool_module = importlib.import_module(
                    f"scenarios.{scenario}.tools.{tool_name}"
                )
                agent_kernel.add_plugin(
                    tool_module.create_plugin(plugin_config), plugin_name=tool_name
                )
            elif tool_type == "openapi":
                openapi_document_path = tool.get("openapi_document_path")
                server_url_override = tool.get("server_url_override")
                agent_kernel.add_plugin_from_openapi(
                    plugin_name=tool_name,
                    openapi_document_path=openapi_document_path,
                    execution_settings=OpenAPIFunctionExecutionParameters(
                        auth_callback=create_auth_callback(chat_ctx),
                        server_url_override=server_url_override,
                        enable_payload_namespacing=True,
                        timeout=None,
                    ),
                )
            else:
                raise ValueError(f"Unknown tool type: {tool_type}")

        if model_supports_temperature():
            temperature = agent_config.get("temperature", DEFAULT_MODEL_TEMP)
            logger.info(
                "Setting model temperature for agent %s to %s",
                agent_config["name"],
                temperature,
            )
        else:
            temperature = None
            logger.info(
                "Model does not support temperature. Setting temperature to None for agent %s",
                agent_config["name"],
            )

        from semantic_kernel.connectors.ai.function_choice_behavior import (
            FunctionChoiceBehavior,
        )

        settings = AzureChatPromptExecutionSettings(
            function_choice_behavior=FunctionChoiceBehavior.Auto(),
            seed=42,
            temperature=temperature,
        )
        arguments = KernelArguments(settings=settings)
        instructions = agent_config.get("instructions")
        if agent_config.get("facilitator") and instructions:
            instructions = instructions.replace(
                "{{aiAgents}}",
                "\n\t\t".join(
                    [
                        f"- {agent['name']}: {agent['description']}"
                        for agent in all_agents_config
                    ]
                ),
            )

        return (
            CustomChatCompletionAgent(
                kernel=agent_kernel,
                name=agent_config["name"],
                instructions=instructions,
                description=agent_config.get("description", ""),
                arguments=arguments,
            )
            if not is_healthcare_agent
            else HealthcareAgent(
                name=agent_config["name"], chat_ctx=chat_ctx, app_ctx=app_ctx
            )
        )

    # Kernel for orchestrator (selection + termination structured decisions)
    orchestrator_kernel = _create_kernel_with_chat_completion()

    # Facilitator (Orchestrator) discovery
    facilitator_agent = next(
        (agent for agent in all_agents_config if agent.get("facilitator")),
        all_agents_config[0],
    )
    facilitator = facilitator_agent["name"]

    # Structured output model config for selection
    selection_settings = AzureChatPromptExecutionSettings(
        function_choice_behavior=FunctionChoiceBehavior.Auto(),
        temperature=DEFAULT_MODEL_TEMP,
        seed=42,
        response_format=ChatRule,
    )
    selection_args = KernelArguments(settings=selection_settings)

    selection_function = KernelFunctionFromPrompt(
        function_name="selection",
        prompt=f"""
        You are overseeing a group chat between several AI agents and a human user.
        Determine which participant takes the next turn based on the most recent participant. Guidelines:

        1. Participants (choose exactly one):
            {"\n".join([("\t- " + agent["name"]) for agent in all_agents_config])}

        2. Rules:
            - {facilitator} always starts if only the user has spoken.
            - Avoid repetition: if an agent already completed its task, don't reselect unless explicitly requested.
            - Agents may request info from each other: if an agent is directly asked by name, that agent goes next.
            - "back to you *AgentName*": that named agent goes next.
            - Each participant speaks at most once per turn.
            - Default to {facilitator} if uncertain or no explicit candidate.
            - Use best judgment for natural conversation flow.
            - CONFIRMATION GATE (PLAN ONLY): If (a) the MOST RECENT message is from {facilitator} AND (b) it contains a multi-step plan (look for "Plan", "plan:", numbered steps like "1.", "2.", or multiple leading "-" bullet lines) AND (c) no user message has appeared AFTER that plan yet, then do NOT advance to another agent. Wait for a user reply. Output {facilitator} ONLY if absolutely necessary to politely prompt the user for confirmation (do not restate the entire plan). As soon as ANY user reply appears (question, modification, or confirmation), this gate is lifted. If the user used a confirmation token (confirm, yes, proceed, continue, ok, okay, sure, sounds good, go ahead), you may advance to the next required non-facilitator agent; otherwise select the participant that best addresses the user’s reply.

        Provide reasoning then the verdict. Verdict must be exactly one of: {", ".join([agent["name"] for agent in all_agents_config])}

        History:
        {{{{$history}}}}
        """,
        prompt_execution_settings=selection_settings,
    )

    termination_settings = AzureChatPromptExecutionSettings(
        function_choice_behavior=FunctionChoiceBehavior.Auto(),
        temperature=DEFAULT_MODEL_TEMP,
        seed=42,
        response_format=ChatRule,
    )
    termination_args = KernelArguments(settings=termination_settings)

    termination_function = KernelFunctionFromPrompt(
        function_name="termination",
        prompt=f"""
        Determine if the conversation should end based on the most recent message only.
        IMPORTANT: In the History, any leading "*AgentName*:" indicates the SPEAKER of the message, not the addressee.

        You are part of a group chat with several AI agents and a user.
        The agent names are:
            {",".join([f"{agent['name']}" for agent in all_agents_config])}

        Return "yes" when the last message:
        - asks the user a question (ends with "?" or uses "you"/"User"), OR
        - invites the user to respond (phrases like: "let us know", "feel free to ask", "what would you like", "should we", "can we", "would you like me to"), OR
        - addresses "we/us" as a decision/query to the user.

        Return "no" when the last message:
        - is a command or question to a specific agent by name, OR
        - is a statement clearly addressed to another agent.

        Commands addressed to "you" or "User" => "yes".
        If uncertain, return "yes".
        Ignore any debug/metadata like "PC_CTX" or JSON blobs.

        Provide reasoning then the verdict ("yes" or "no").

        History:
        {{{{$history}}}}
        """,
        prompt_execution_settings=termination_settings,
    )

    agents = [_create_agent(agent) for agent in all_agents_config]

    def evaluate_termination(result):
        """Evaluate termination decision from structured output."""
        try:
            rule = ChatRule.model_validate_json(str(result.value[0]))
            should_terminate = rule.verdict == "yes"
            logger.debug(
                "Termination decision: %s | Reasoning: %s",
                should_terminate,
                rule.reasoning,
            )
            return should_terminate
        except Exception as e:
            logger.error("Termination function error: %s", e)
            return False

    def evaluate_selection(result):
        """Evaluate agent selection from structured output."""
        try:
            rule = ChatRule.model_validate_json(str(result.value[0]))
            selected_agent = (
                rule.verdict
                if rule.verdict
                in [agent["name"] for agent in all_agents_config]
                else facilitator
            )
            logger.debug(
                "Selected agent: %s | Reasoning: %s", selected_agent, rule.reasoning
            )
            return selected_agent
        except Exception as e:
            logger.error("Selection function error: %s", e)
            return facilitator

    chat = AgentGroupChat(
        agents=agents,
        chat_history=chat_ctx.chat_history,
        selection_strategy=KernelFunctionSelectionStrategy(
            function=selection_function,
            kernel=orchestrator_kernel,
            result_parser=evaluate_selection,
            agent_variable_name="agents",
            history_variable_name="history",
            arguments=selection_args,
        ),
        termination_strategy=KernelFunctionTerminationStrategy(
            agents=[agent for agent in agents if agent.name == facilitator],
            function=termination_function,
            kernel=orchestrator_kernel,
            result_parser=evaluate_termination,
            agent_variable_name="agents",
            history_variable_name="history",
            maximum_iterations=30,
            history_reducer=ChatHistoryTruncationReducer(target_count=1, auto_reduce=True),
            arguments=termination_args,
        ),
    )

    logger.info("Group chat created successfully with %d agents", len(agents))
    return (chat, chat_ctx)

# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import importlib
import logging
import os
from typing import Any, Awaitable, Callable, Tuple

from pydantic import BaseModel
from semantic_kernel import Kernel
from semantic_kernel.agents import AgentGroupChat, ChatCompletionAgent
from semantic_kernel.agents.strategies.selection.kernel_function_selection_strategy import \
    KernelFunctionSelectionStrategy
from semantic_kernel.agents.strategies.termination.kernel_function_termination_strategy import \
    KernelFunctionTerminationStrategy
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import \
    AzureChatPromptExecutionSettings
from semantic_kernel.connectors.ai.open_ai.services.azure_chat_completion import AzureChatCompletion
from semantic_kernel.connectors.openapi_plugin import OpenAPIFunctionExecutionParameters
from semantic_kernel.contents.history_reducer.chat_history_truncation_reducer import ChatHistoryTruncationReducer
from semantic_kernel.functions.kernel_function_from_prompt import KernelFunctionFromPrompt
from semantic_kernel.kernel import Kernel, KernelArguments

from data_models.app_context import AppContext
from data_models.chat_context import ChatContext
from data_models.plugin_configuration import PluginConfiguration
from healthcare_agents import HealthcareAgent
from healthcare_agents import config as healthcare_agent_config


DEFAULT_MODEL_TEMP = 0
DEFAULT_TOOL_TYPE = "function"

logger = logging.getLogger(__name__)


class ChatRule(BaseModel):
    verdict: str
    reasoning: str


def create_auth_callback(chat_ctx: ChatContext) -> Callable[..., Awaitable[Any]]:
    """
    Creates an authentication callback for the plugin configuration.

    :param chat_ctx: The chat context to be used in the authentication.
    :return: A callable that returns an authentication token.
    """
    # TODO - get key or secret from Azure Key Vault for OpenAPI services.
    # Send the conversation ID as a header to the OpenAPI service.
    return lambda: {'conversation-id': chat_ctx.conversation_id, }


def create_group_chat(
    app_ctx: AppContext, chat_ctx: ChatContext, participants: list[dict] = None
) -> Tuple[AgentGroupChat, ChatContext]:
    participant_configs = participants or app_ctx.all_agent_configs
    participant_names = [cfg.get("name") for cfg in participant_configs]
    logger.info(f"Creating group chat with participants: {participant_names}")

    # Remove magentic agent from the list of agents. In the future, we could add agent type to deal with agents that should not be included in the Semantic Kernel group chat.
    all_agents_config = [
        agent for agent in participant_configs if agent.get("name") != "magentic"
    ]

    def _create_kernel_with_chat_completion() -> Kernel:
        kernel = Kernel()
        kernel.add_service(
            AzureChatCompletion(
                service_id="default",
                deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
                api_version="2024-10-21",
                ad_token_provider=app_ctx.cognitive_services_token_provider
            )
        )
        return kernel

    def _create_agent(agent_config: dict):
        agent_kernel = _create_kernel_with_chat_completion()
        plugin_config = PluginConfiguration(
            kernel=agent_kernel,
            agent_config=agent_config,
            data_access=app_ctx.data_access,
            chat_ctx=chat_ctx,
            azureml_token_provider=app_ctx.azureml_token_provider,
        )
        is_healthcare_agent = healthcare_agent_config.yaml_key in agent_config and bool(
            agent_config[healthcare_agent_config.yaml_key])

        for tool in agent_config.get("tools", []):
            tool_name = tool.get("name")
            tool_type = tool.get("type", DEFAULT_TOOL_TYPE)

            # Add function tools
            if tool_type == "function":
                scenario = os.environ.get("SCENARIO")
                tool_module = importlib.import_module(f"scenarios.{scenario}.tools.{tool_name}")
                agent_kernel.add_plugin(tool_module.create_plugin(plugin_config), plugin_name=tool_name)
            # Add OpenAPI tools
            # See https://github.com/Azure-Samples/healthcare-agent-orchestrator/blob/main/docs/agent_development.md#agent-with-a-openapi-plugin-example
            elif tool_type == "openapi":
                openapi_document_path = tool.get("openapi_document_path")
                server_url_override = tool.get("server_url_override")
                agent_kernel.add_plugin_from_openapi(
                    plugin_name=tool_name,
                    openapi_document_path=openapi_document_path,
                    execution_settings=OpenAPIFunctionExecutionParameters(
                        auth_callback=create_auth_callback(chat_ctx),
                        server_url_override=server_url_override,
                        enable_payload_namespacing=True
                    )
                )
            else:
                raise ValueError(f"Unknown tool type: {tool_type}")

        temperature = agent_config.get("temperature", DEFAULT_MODEL_TEMP)
        settings = AzureChatPromptExecutionSettings(
            function_choice_behavior=FunctionChoiceBehavior.Auto(), temperature=temperature, seed=42)
        arguments = KernelArguments(settings=settings)
        instructions = agent_config.get("instructions")
        if agent_config.get("facilitator") and instructions:
            instructions = instructions.replace(
                "{{aiAgents}}", "\n\t\t".join([f"- {agent['name']}: {agent["description"]}" for agent in all_agents_config]))

        return (ChatCompletionAgent(service_id="default",
                                    kernel=agent_kernel,
                                    name=agent_config["name"],
                                    instructions=instructions,
                                    arguments=arguments) if not is_healthcare_agent else
                HealthcareAgent(name=agent_config["name"],
                                chat_ctx=chat_ctx,
                                app_ctx=app_ctx))

    settings = AzureChatPromptExecutionSettings(
        function_choice_behavior=FunctionChoiceBehavior.Auto(), temperature=DEFAULT_MODEL_TEMP, seed=42, response_format=ChatRule)
    arguments = KernelArguments(settings=settings)

    facilitator_agent = next((agent for agent in all_agents_config if agent.get("facilitator")), all_agents_config[0])
    facilitator = facilitator_agent["name"]
    selection_function = KernelFunctionFromPrompt(
        function_name="selection",
        prompt=f"""
        You are overseeing a group chat between several AI agents and a human user.
        Determine which participant takes the next turn in a conversation based on the most recent participant. Follow these guidelines:

        1. **Participants**: Choose only from these participants:
            {"\n".join([("\t- " + agent["name"]) for agent in all_agents_config])}

        2. **General Rules**:
            - **{facilitator} Always Starts**: {facilitator} always goes first to formulate a plan. If the only message is from the user, {facilitator} goes next.
            - **Interactions between agents**: Agents may talk among themselves. If an agent requires information from another agent, that agent should go next.
                EXAMPLE:
                    "*agent_name*, please provide ..." then agent_name goes next.
            - **"back to you *agent_name*": If an agent says "back to you", that agent goes next.
                EXAMPLE:
                    "back to you *agent_name*" then output agent_name goes next.
            - **Once per turn**: Each participant can only speak once per turn.
            - **Default to {facilitator}**: Always default to {facilitator}. If no other participant is specified, {facilitator} goes next.
            - **Use best judgment**: If the rules are unclear, use your best judgment to determine who should go next, for the natural flow of the conversation.
            
        Provide your reasoning and then the verdict. The verdict must be exactly one of: {", ".join([agent["name"] for agent in all_agents_config])}

        History:
        {{{{$history}}}}
        """,
        prompt_execution_settings=settings
    )

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
        - invites the user to respond (e.g., "let us know", "how can we assist/help", "feel free to ask",
            "what would you like", "should we", "can we", "would you like me to", "do you want me to"), OR
        - addresses "we/us" as a decision/query to the user.

        Return "no" when the last message:
        - is a command or question to a specific agent by name, OR
        - is a statement addressed to another agent.

        Commands addressed to "you" or "User" => "yes".
        If you are uncertain, return "yes".
        Ignore any debug/metadata like "PC_CTX" or JSON blobs when deciding.
        
        Provide your reasoning and then the verdict. The verdict must be exactly "yes" or "no".

        EXAMPLES:
        - "User, can you confirm the correct patient ID?" => verdict: "yes" (Asks user a direct question)
        - "*ReportCreation*: Please compile the patient timeline." => verdict: "no" (Command to specific agent ReportCreation)
        - "If you have any further questions, feel free to ask." => verdict: "yes" (Invites user to respond)

        History:
        {{{{$history}}}}
        """,
        prompt_execution_settings=settings
    )
    agents = [_create_agent(agent) for agent in all_agents_config]

    def evaluate_termination(result):
        logger.info(f"Termination function result: {result}")
        try:
            rule = ChatRule.model_validate_json(str(result.value[0]))
            should_terminate = rule.verdict == "yes"
            logger.info(f"Termination function parsed successfully: {should_terminate}")
            return should_terminate
        except Exception as e:
            logger.error(f"Termination function parsing error: {e}. Raw result: {result}")
            return False  # Fallback to continue conversation

    def evaluate_selection(result):
        logger.info(f"Selection function result: {result}")
        try:
            rule = ChatRule.model_validate_json(str(result.value[0]))
            selected_agent = rule.verdict if rule.verdict in [agent["name"]
                                                              for agent in all_agents_config] else facilitator
            logger.info(f"Selection function parsed successfully: {selected_agent}")
            return selected_agent
        except Exception as e:
            logger.error(f"Selection function parsing error: {e}. Raw result: {result}")
            return facilitator  # Fallback to facilitator

    chat = AgentGroupChat(
        agents=agents,
        chat_history=chat_ctx.chat_history,
        selection_strategy=KernelFunctionSelectionStrategy(
            function=selection_function,
            kernel=_create_kernel_with_chat_completion(),
            result_parser=evaluate_selection,
            agent_variable_name="agents",
            history_variable_name="history",
            arguments=arguments,
        ),
        termination_strategy=KernelFunctionTerminationStrategy(
            agents=[
                agent for agent in agents if agent.name == facilitator
            ],  # Only facilitator decides if the conversation ends
            function=termination_function,
            kernel=_create_kernel_with_chat_completion(),
            result_parser=evaluate_termination,
            agent_variable_name="agents",
            history_variable_name="history",
            maximum_iterations=30,
            # Termination only looks at the last message
            history_reducer=ChatHistoryTruncationReducer(
                target_count=1, auto_reduce=True
            ),
            arguments=arguments,
        ),
    )

    return (chat, chat_ctx)

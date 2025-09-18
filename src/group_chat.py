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
from semantic_kernel.agents.strategies.selection.kernel_function_selection_strategy import \
    KernelFunctionSelectionStrategy
from semantic_kernel.agents.strategies.termination.kernel_function_termination_strategy import \
    KernelFunctionTerminationStrategy
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import \
    AzureChatPromptExecutionSettings
from semantic_kernel.connectors.ai.open_ai.services.azure_chat_completion import AzureChatCompletion
from semantic_kernel.connectors.openapi_plugin import OpenAPIFunctionExecutionParameters
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.contents.history_reducer.chat_history_truncation_reducer import ChatHistoryTruncationReducer
from semantic_kernel.functions.kernel_function_from_prompt import KernelFunctionFromPrompt
from semantic_kernel.kernel import Kernel, KernelArguments
from semantic_kernel.contents import AuthorRole, ChatMessageContent
from semantic_kernel.contents import TextContent

from data_models.app_context import AppContext
from data_models.chat_context import ChatContext
from data_models.plugin_configuration import PluginConfiguration
from data_models.patient_context_models import WorkflowSummary
from healthcare_agents import HealthcareAgent
from healthcare_agents import config as healthcare_agent_config


DEFAULT_MODEL_TEMP = 0
DEFAULT_TOOL_TYPE = "function"

logger = logging.getLogger(__name__)


class CustomHistoryChannel(ChatHistoryChannel):
    @override
    async def receive(self, history: list[ChatMessageContent],) -> None:
        await super().receive(history)
        for message in history[:-1]:
            await self.thread.on_new_message(message)


class CustomChatCompletionAgent(ChatCompletionAgent):
    """Custom ChatCompletionAgent to override the create_channel method."""

    @override
    async def create_channel(
        self, chat_history: ChatHistory | None = None, thread_id: str | None = None
    ) -> CustomHistoryChannel:
        from semantic_kernel.agents.chat_completion.chat_completion_agent import ChatHistoryAgentThread

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
    """
    Creates an authentication callback for the plugin configuration.

    Args:
        chat_ctx: The chat context to be used in the authentication.

    Returns:
        A callable that returns an authentication token.
    """
    return lambda: {'conversation-id': chat_ctx.conversation_id, }


def inject_workflow_summary(chat_ctx: ChatContext) -> None:
    """Inject workflow summary if available."""
    if (hasattr(chat_ctx, 'workflow_summary') and
        chat_ctx.workflow_summary and
            chat_ctx.patient_id):

        # Check if already injected
        for msg in chat_ctx.chat_history.messages:
            if (msg.role == AuthorRole.SYSTEM and
                isinstance(msg.content, str) and
                    "WORKFLOW_SUMMARY:" in msg.content):
                return

        # Inject summary with proper items initialization
        summary_message = ChatMessageContent(
            role=AuthorRole.SYSTEM,
            items=[TextContent(text=f"WORKFLOW_SUMMARY: {chat_ctx.workflow_summary}")]
        )
        chat_ctx.chat_history.messages.insert(1, summary_message)
        logger.info(f"Injected workflow summary for patient {chat_ctx.patient_id}")


async def generate_workflow_summary(
    chat_ctx: ChatContext,
    kernel: Kernel,
    patient_id: str,
    objective: str
) -> WorkflowSummary:
    """
    Generate structured workflow summary using WorkflowSummary model.
    This implements structured output for workflow planning.

    Args:
        chat_ctx: The chat context for conversation history
        kernel: Semantic kernel instance for LLM interaction
        patient_id: The patient identifier
        objective: The main workflow objective

    Returns:
        WorkflowSummary: Structured workflow with agent assignments and tasks
    """

    # Build context from chat history
    recent_messages = chat_ctx.chat_history.messages[-10:] if len(
        chat_ctx.chat_history.messages) > 10 else chat_ctx.chat_history.messages
    context = "\n".join([f"{msg.role}: {msg.content}" for msg in recent_messages])

    workflow_prompt = f"""
    You are a healthcare workflow coordinator. Analyze the conversation and create a structured workflow summary.
    
    CONTEXT:
    - Patient ID: {patient_id}
    - Objective: {objective}
    - Recent conversation: {context}
    
    Create a workflow with specific steps for each agent to follow. Each step should:
    1. Assign a specific agent (PatientHistory, ClinicalGuidelines, MedicalResearch, etc.)
    2. Define a clear task for that agent
    3. Set appropriate status (pending, in_progress, completed)
    
    Focus on the main healthcare objective and break it into logical agent-specific steps.
    Keep reasoning concise and actionable.
    """

    try:
        chat_history = ChatHistory()
        chat_history.add_system_message(workflow_prompt)

        # Use structured output for workflow planning
        execution_settings = AzureChatPromptExecutionSettings(
            service_id="default",
            max_tokens=500,
            temperature=0.2,
            response_format=WorkflowSummary,  # This generates the JSON schema automatically
        )

        svc = kernel.get_service("default")
        results = await svc.get_chat_message_contents(
            chat_history=chat_history,
            settings=execution_settings,
        )

        if not results or not results[0].content:
            logger.warning("No workflow summary generated")
            # Fallback workflow
            from data_models.patient_context_models import WorkflowStep
            return WorkflowSummary(
                patient_id=patient_id,
                objective=objective,
                steps=[
                    WorkflowStep(agent="Orchestrator", task="Coordinate healthcare workflow", status="pending")
                ],
                current_step=0,
                reasoning="Fallback workflow due to generation failure"
            )

        content = results[0].content

        # Parse structured response
        if isinstance(content, str):
            try:
                workflow = WorkflowSummary.model_validate_json(content)
            except Exception as e:
                logger.error(f"Failed to parse workflow summary: {e}")
                # Return fallback
                from data_models.patient_context_models import WorkflowStep
                return WorkflowSummary(
                    patient_id=patient_id,
                    objective=objective,
                    steps=[WorkflowStep(agent="Orchestrator", task="Coordinate workflow", status="pending")],
                    current_step=0,
                    reasoning=f"Parse error: {str(e)[:30]}..."
                )
        elif isinstance(content, dict):
            try:
                workflow = WorkflowSummary.model_validate(content)
            except Exception as e:
                logger.error(f"Failed to validate workflow summary: {e}")
                from data_models.patient_context_models import WorkflowStep
                return WorkflowSummary(
                    patient_id=patient_id,
                    objective=objective,
                    steps=[WorkflowStep(agent="Orchestrator", task="Coordinate workflow", status="pending")],
                    current_step=0,
                    reasoning=f"Validation error: {str(e)[:30]}..."
                )
        else:
            logger.warning(f"Unexpected workflow response type: {type(content)}")
            from data_models.patient_context_models import WorkflowStep
            return WorkflowSummary(
                patient_id=patient_id,
                objective=objective,
                steps=[WorkflowStep(agent="Orchestrator", task="Coordinate workflow", status="pending")],
                current_step=0,
                reasoning="Unexpected response format"
            )

        logger.info(f"Generated workflow summary with {len(workflow.steps)} steps for patient {patient_id}")
        return workflow

    except Exception as e:
        logger.error(f"Workflow summary generation failed: {e}")
        from data_models.patient_context_models import WorkflowStep
        return WorkflowSummary(
            patient_id=patient_id,
            objective=objective,
            steps=[WorkflowStep(agent="Orchestrator", task="Coordinate workflow", status="pending")],
            current_step=0,
            reasoning=f"Generation error: {str(e)[:30]}..."
        )


def create_group_chat(
    app_ctx: AppContext, chat_ctx: ChatContext, participants: list[dict] = None
) -> Tuple[AgentGroupChat, ChatContext]:
    """
    Create a multi-agent group chat with structured output strategies.

    Args:
        app_ctx: Application context containing shared resources
        chat_ctx: Chat context for conversation state
        participants: Optional list of participant configurations

    Returns:
        Tuple of AgentGroupChat instance and updated ChatContext
    """
    participant_configs = participants or app_ctx.all_agent_configs
    participant_names = [cfg.get("name") for cfg in participant_configs]
    logger.info(f"Creating group chat with participants: {participant_names}")

    # Inject workflow summary before creating agents
    inject_workflow_summary(chat_ctx)

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
                api_version="2024-10-21",
                ad_token_provider=app_ctx.cognitive_services_token_provider
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

        return (CustomChatCompletionAgent(kernel=agent_kernel,
                                          name=agent_config["name"],
                                          instructions=instructions,
                                          description=agent_config.get("description", ""),
                                          arguments=arguments) if not is_healthcare_agent else
                HealthcareAgent(name=agent_config["name"],
                                chat_ctx=chat_ctx,
                                app_ctx=app_ctx))

    # Create kernel for orchestrator functions
    orchestrator_kernel = _create_kernel_with_chat_completion()

    # Find facilitator agent
    facilitator_agent = next((agent for agent in all_agents_config if agent.get("facilitator")), all_agents_config[0])
    facilitator = facilitator_agent["name"]

    # Structured output for selection/termination decisions
    settings = AzureChatPromptExecutionSettings(
        function_choice_behavior=FunctionChoiceBehavior.Auto(),
        temperature=DEFAULT_MODEL_TEMP,
        seed=42,
        response_format=ChatRule
    )
    arguments = KernelArguments(settings=settings)

    async def create_workflow_summary_if_needed():
        """Generate workflow summary for new patient workflows."""
        if chat_ctx.patient_id and not hasattr(chat_ctx, 'workflow_summary'):
            # Determine objective from recent conversation
            objective = "Provide comprehensive healthcare assistance"
            if len(chat_ctx.chat_history.messages) > 0:
                last_msg = chat_ctx.chat_history.messages[-1].content
                if isinstance(last_msg, str) and len(last_msg) > 10:
                    objective = f"Address user request: {last_msg[:100]}..."

            workflow = await generate_workflow_summary(
                chat_ctx=chat_ctx,
                kernel=orchestrator_kernel,
                patient_id=chat_ctx.patient_id,
                objective=objective
            )

            # Store workflow summary in chat context
            chat_ctx.workflow_summary = workflow.model_dump_json()
            logger.info(f"Generated new workflow summary for patient {chat_ctx.patient_id}")

    selection_function = KernelFunctionFromPrompt(
        function_name="selection",
        prompt=f"""
        You are overseeing a group chat between several AI agents and a human user.
        Determine which participant takes the next turn in a conversation based on the most recent participant. Follow these guidelines:

        1. **Participants**: Choose only from these participants:
            {"\n".join([("\t- " + agent["name"]) for agent in all_agents_config])}

        2. **General Rules**:
            - **{facilitator} Always Starts**: {facilitator} always goes first to formulate a plan. If the only message is from the user, {facilitator} goes next.
            - **Check Workflow Progress**: Look for WORKFLOW_SUMMARY messages to understand what stage of the process we're in
            - **Avoid Repetition**: If an agent has already completed their task (according to workflow summary), don't select them again unless specifically requested
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
        """Evaluate termination decision from structured output."""
        try:
            rule = ChatRule.model_validate_json(str(result.value[0]))
            should_terminate = rule.verdict == "yes"
            logger.debug(f"Termination decision: {should_terminate} | Reasoning: {rule.reasoning}")
            return should_terminate
        except Exception as e:
            logger.error(f"Termination function error: {e}")
            return False  # Fallback to continue conversation

    def evaluate_selection(result):
        """Evaluate agent selection from structured output."""
        try:
            rule = ChatRule.model_validate_json(str(result.value[0]))
            selected_agent = rule.verdict if rule.verdict in [agent["name"]
                                                              for agent in all_agents_config] else facilitator
            logger.debug(f"Selected agent: {selected_agent} | Reasoning: {rule.reasoning}")
            return selected_agent
        except Exception as e:
            logger.error(f"Selection function error: {e}")
            return facilitator  # Fallback to facilitator

    chat = AgentGroupChat(
        agents=agents,
        chat_history=chat_ctx.chat_history,
        selection_strategy=KernelFunctionSelectionStrategy(
            function=selection_function,
            kernel=orchestrator_kernel,
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
            kernel=orchestrator_kernel,
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

    logger.info(f"Group chat created successfully with {len(agents)} agents")
    return (chat, chat_ctx)

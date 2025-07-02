import logging
import re
from typing import Any, Dict, List

from semantic_kernel.connectors.ai.open_ai.services.azure_chat_completion import AzureChatCompletion
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.contents.utils.author_role import AuthorRole

from .base import AgentLLMasJudge


class TurnByTurnAgentSelectionEvaluator(AgentLLMasJudge):
    """Evaluates each individual agent selection decision by the orchestrator."""

    DEFAULT_SYSTEM_PROMPT = """
You are an expert evaluator of medical AI assistants. Your task is to evaluate a single agent selection decision made by the AI orchestrator (called "Orchestrator") in a medical conversation.

The available agents are:
- researchagent: Handles research-related queries and academic information
- clinicaltrials: Provides information about clinical trials
- summary: Creates medical summaries
- treatment: Provides treatment-related information and recommendations
- patientstatus: Reports on patient's current medical status
- pathology: Handles pathology reports and interpretations
- radiology: Handles radiology reports and interpretations
- dataorganizer: Organizes and presents patient data

Focus on whether this specific agent selection was appropriate for the context. Consider:
1. Was this agent the most appropriate choice for the current user query or conversation state?
2. Could a different agent have been more suitable?
3. Was this agent's expertise relevant to the task at hand?
4. Was using this agent necessary, or could the orchestrator have handled it directly?

Rate the agent selection decision on a scale from 1 to 5:
1: Poor - Completely inappropriate agent selection that doesn't match the task
2: Below Average - Suboptimal agent choice when better options were available
3: Average - Acceptable agent choice but not necessarily optimal
4: Good - Appropriate agent selection that matches the task well
5: Excellent - Perfect agent selection that optimally matches the task requirements

Your response must begin with "Rating: X" where X is your score (1-5), followed by your detailed explanation.
"""

    def __init__(self,
                 evaluation_llm_service: AzureChatCompletion,
                 system_prompt: str = None,
                 metric_name: str = "turn_by_turn_agent_selection",
                 description: str = "Evaluates each individual agent selection decision by the orchestrator",
                 agent_name: str = "Orchestrator",
                 scenario: str = "default"):
        """
        Initialize the evaluator.

        Args:
            evaluation_llm_service: LLM service for evaluation
            system_prompt: Custom system prompt
            metric_name: Name of the metric
            description: Metric description
            agent_name: Name of the orchestrator agent
            scenario: Name of the scenario folder
        """
        super().__init__(
            evaluation_llm_service=evaluation_llm_service,
            agent_name=agent_name,
            context_window=3
        )
        self.planned_agents = []
        self._system_prompt = system_prompt
        self._metric_name = metric_name
        self._description = description

        # Load valid agents dynamically from config
        self.valid_agents = self.load_valid_agents(scenario)

    @property
    def system_prompt(self) -> str:
        """Return custom system prompt if provided, otherwise return default."""
        return self._system_prompt or self.DEFAULT_SYSTEM_PROMPT

    @property
    def name(self) -> str:
        """Return custom metric name."""
        return self._metric_name

    @property
    def description(self) -> str:
        """Return custom description."""
        return self._description

    @property
    def min_score(self) -> int:
        return 1

    @property
    def max_score(self) -> int:
        return 5

    def process_rating(self, content: str) -> int:
        """Extract the rating from LLM response content."""
        # Look for "Rating: X" at the start of the response
        match = re.match(r"Rating:\s*([1-5])", content)
        if match:
            return int(match.group(1))
        # Fall back to default extraction if pattern not found
        return self.default_rating_extraction(content)

    def _extract_planned_agents(self, message: str) -> List[str]:
        """Extract agent names from orchestrator's plan message."""
        # Look for agent names in format: **agentname**
        agents = re.findall(r'\*\*([\w-]+)\*\*', message)
        # Filter using dynamically loaded valid agents
        return [agent for agent in agents if agent.lower() in self.valid_agents]

    def _split_chat_history(self, chat_history: ChatHistory) -> list[ChatHistory]:
        """
        Split the chat history into segments that represent complete interactions.
        A complete interaction must have:
        1. Either a user query OR an orchestrator message (trigger)
        2. Selected agent's response
        3. Any follow-up agent interactions completed
        """
        segments = []
        messages = [msg for msg in chat_history.messages if msg.content]

        current_segment = ChatHistory()
        current_trigger = None
        current_orchestrator = None
        last_agent = None

        for i, msg in enumerate(messages):
            if msg.role == AuthorRole.USER:
                # Start new segment on user message
                if current_segment.messages:
                    segments.append(current_segment)
                current_segment = ChatHistory()
                current_trigger = msg
                current_segment.add_message(msg)
                current_orchestrator = None

            elif msg.name == "Orchestrator":
                # Extract planned agents if this is an initial plan
                if "**" in msg.content:
                    agents = self._extract_planned_agents(msg.content)
                    self.planned_agents.extend(agents)

                current_orchestrator = msg
                current_segment.add_message(msg)

            elif msg.role == AuthorRole.ASSISTANT and msg.name != "Orchestrator":
                # Add agent response if it's either:
                # 1. A direct response to orchestrator
                # 2. A planned agent from initial outline
                # 3. An agent-to-agent interaction helping complete the task
                if (current_orchestrator or
                    msg.name in self.planned_agents or
                        (last_agent and last_agent != msg.name)):
                    current_segment.add_message(msg)
                    last_agent = msg.name

                # Complete segment if we have a valid interaction
                if len(current_segment.messages) >= 2:
                    new_segment = ChatHistory()
                    for message in current_segment.messages:
                        new_segment.add_message(message)
                    segments.append(new_segment)

                    # Start new segment preserving context
                    current_segment = ChatHistory()
                    current_orchestrator = None

        return segments

    async def evaluate(self, chat_history: ChatHistory, patient_id: str | None = None) -> List[Dict[str, Any]]:
        """
        Evaluate agent selection decisions in the chat history.
        Called by Evaluator._evaluate() through the metric interface.
        """
        # Get raw evaluation results from parent class (AgentLLMasJudge)
        all_results = await super().evaluate(chat_history, patient_id)

        # Filter and restructure results
        complete_results = []
        valid_scores = []

        for result in all_results:
            if "error" not in result.get("details", {}):
                # Extract valid scores
                score = result.get("score", 0)
                if score > 0:
                    valid_scores.append(score)

                # Restructure to match expected format
                complete_results.append({
                    "result": {
                        "score": score,
                        "explanation": result["explanation"],
                        "details": result.get("details", {})
                    },
                    "id": patient_id,
                    "patient_id": patient_id
                })

        # Log evaluation stats for this chat history
        num_valid = len(valid_scores)
        num_total = len(all_results)
        avg_score = sum(valid_scores) / num_valid if num_valid > 0 else 0
        logging.info(
            f"Turn-by-turn evaluation for chat {patient_id}: {num_valid} valid scores (avg: {avg_score:.2f}) out of {num_total} total")

        return complete_results

    async def _evaluate_segment(self, segment: ChatHistory, patient_id: str | None = None) -> list[dict[str, Any]]:
        """Evaluate one agent selection decision."""
        # Extract key elements from the segment
        user_query = None
        orchestrator_message = None
        selected_agent = None
        agent_response = None

        for msg in segment.messages:
            if not msg.content:
                continue

            if msg.role == AuthorRole.USER:
                user_query = msg.content
            elif msg.name == "Orchestrator":
                orchestrator_message = msg.content
            elif msg.role == AuthorRole.ASSISTANT and msg.name != "Orchestrator":
                selected_agent = msg.name
                agent_response = msg.content

        # Valid interaction if we have:
        # 1. Either user query OR orchestrator message (trigger)
        # 2. Selected agent (either direct or from plan)
        # 3. Agent response
        if not ((user_query or orchestrator_message) and selected_agent and agent_response):
            missing = []
            if not (user_query or orchestrator_message):
                missing.append("trigger")
            if not selected_agent:
                missing.append("selected agent")
            if not agent_response:
                missing.append("agent response")

            return [{
                "score": 0,
                "explanation": f"Error: Incomplete interaction - missing {', '.join(missing)}",
                "details": {
                    "error": f"Incomplete interaction - missing {', '.join(missing)}"
                }
            }]

        # Use parent class for LLM evaluation
        result = await super()._evaluate_segment(segment, patient_id)

        # Add interaction details to results
        for r in result:
            r.update({
                "details": {
                    "user_query": user_query,
                    "orchestrator_message": orchestrator_message,
                    "selected_agent": selected_agent,
                    "agent_response": agent_response,
                    "patient_id": patient_id,
                    "is_planned_agent": selected_agent in self.planned_agents
                }
            })

        return result

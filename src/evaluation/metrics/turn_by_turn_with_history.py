import logging
import re
from typing import Any, Dict, List

from semantic_kernel.connectors.ai.open_ai.services.azure_chat_completion import AzureChatCompletion
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.contents.utils.author_role import AuthorRole

from .base import AgentLLMasJudge


class TurnByTurnEvaluatorWithContext(AgentLLMasJudge):
    """Evaluates each turn with conversation context."""

    VALID_METRIC_NAMES = {
        "turn_by_turn_agent_selection",
        "turn_by_turn_intent_resolution",
        "turn_by_turn_information_aggregation"
    }

    def __init__(self,
                 evaluation_llm_service: AzureChatCompletion,
                 system_prompt: str = None,
                 metric_name: str = "turn_by_turn_agent_selection",
                 description: str = None,
                 agent_name: str = "Orchestrator",
                 context_window: int = 3):
        """Initialize the evaluator with optional custom system prompt and metric name."""
        super().__init__(
            evaluation_llm_service=evaluation_llm_service,
            agent_name=agent_name,
            context_window=context_window
        )

        if metric_name not in self.VALID_METRIC_NAMES:
            raise ValueError(
                f"Invalid metric name: {metric_name}. Must be one of: {', '.join(self.VALID_METRIC_NAMES)}")

        self.planned_agents = []  # Will be populated during evaluation
        self._system_prompt = system_prompt
        self._metric_name = metric_name
        self._description = description or f"Evaluates {metric_name.replace('turn_by_turn_', '')} for each turn"

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
        """
        Extract agent names from orchestrator's message using multiple patterns.
        Returns empty list if no agents found.
        """
        agents = set()

        # Pattern 1: **agentname**
        bold_agents = re.findall(r'\*\*([\w-]+)\*\*', message)
        agents.update(bold_agents)

        # Pattern 2: *agentname*
        italic_agents = re.findall(r'\*([\w-]+)\*(?!\*)', message)
        agents.update(italic_agents)

        # Pattern 3: Look for agent names in plain text
        valid_agents = {
            "dataorganizer", "radiology", "patientstatus", "treatment",
            "summary", "researchagent", "clinicaltrials", "pathology",
            "alba-paige-pathology"  # Add any other known agents
        }

        # Convert to lowercase for case-insensitive matching
        agents_lower = {agent.lower() for agent in agents}

        # Only keep valid agent names
        valid_matches = {agent for agent in agents_lower if agent in valid_agents}

        if not valid_matches:
            logging.warning(f"No valid agents found in message: {message[:100]}...")

        return sorted(list(valid_matches))

    def _split_chat_history(self, chat_history: ChatHistory) -> list[ChatHistory]:
        """Split chat history into progressive turns while maintaining all context."""
        segments = []
        messages = [msg for msg in chat_history.messages if msg.content]

        # Track conversation progress
        accumulated_messages = []
        current_segment = ChatHistory()
        i = 0

        while i < len(messages):
            msg = messages[i]
            accumulated_messages.append(msg)

            # Handle conversation segments
            if msg.role == AuthorRole.USER:
                if current_segment.messages:
                    # Create segment with all previous context
                    context_segment = self._create_progressive_segment(accumulated_messages[:-1], current_segment)
                    segments.append(context_segment)
                    current_segment = ChatHistory()
                current_segment.add_message(msg)

            elif msg.name == self.agent_name:
                current_segment.add_message(msg)

                # Look ahead for agent responses
                j = i + 1
                while j < len(messages):
                    next_msg = messages[j]
                    if next_msg.role == AuthorRole.USER:
                        break
                    if next_msg.role == AuthorRole.ASSISTANT:
                        current_segment.add_message(next_msg)
                        accumulated_messages.append(next_msg)
                    j += 1
                i = j - 1

                # Add completed segment with full context
                context_segment = self._create_progressive_segment(accumulated_messages, current_segment)
                segments.append(context_segment)
                current_segment = ChatHistory()

            i += 1

        # Add final segment if not empty
        if current_segment.messages:
            context_segment = self._create_progressive_segment(accumulated_messages, current_segment)
            segments.append(context_segment)

        return segments

    def _create_progressive_segment(self, context_messages: list, current_segment: ChatHistory) -> ChatHistory:
        """Create new segment with full conversation context."""
        new_segment = ChatHistory()

        # Add all context messages from previous turns
        for msg in context_messages:
            if msg not in current_segment.messages:
                new_segment.add_message(msg)

        # Add current segment messages
        for msg in current_segment.messages:
            new_segment.add_message(msg)

        return new_segment

    def create_context_summary(self, history: ChatHistory) -> dict:
        """Create structured summary focusing on conversation context and flow."""
        return {
            "num_turns": len([m for m in history.messages if m.role == AuthorRole.USER]),
            "agents_involved": self._get_unique_agents(history),
            "conversation_flow": self._summarize_conversation_flow(history)
        }

    def _summarize_conversation_flow(self, history: ChatHistory) -> str:
        """Summarize the progressive flow of conversation."""
        flow = []

        for msg in history.messages:
            if msg.role == AuthorRole.USER:
                flow.append("USER query")
            elif msg.name == "Orchestrator":
                flow.append("ORCHESTRATOR response")
            elif msg.role == AuthorRole.ASSISTANT:
                flow.append(f"{msg.name} response")

        return " > ".join(flow)

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
        """Evaluate one segment with context."""
        # Extract messages maintaining sequence
        latest_messages = []
        for msg in segment.messages:
            if not msg.content:
                continue

            if msg.role == AuthorRole.USER:
                # Include all user messages to maintain conversation flow
                latest_messages.append(msg)
            elif msg.name == self.agent_name:  # Use instance attribute
                # Add orchestrator message if not already present
                if not any(m for m in latest_messages if m.name == self.agent_name):
                    latest_messages.append(msg)
            elif msg.role == AuthorRole.ASSISTANT and msg.name != self.agent_name:
                # Add agent responses if not already present
                if not any(m for m in latest_messages if m.name == msg.name):
                    latest_messages.append(msg)

        # Create context summary
        context_summary = self.create_context_summary(segment)

        # Create evaluation segment with context
        eval_segment = ChatHistory()
        eval_segment.add_system_message(
            f"Previous conversation context ({context_summary['num_turns']} turns):\n" +
            f"Agents involved: {', '.join(context_summary['agents_involved'])}\n" +
            f"Conversation flow: {context_summary['conversation_flow']}"
        )

        # Add all messages maintaining sequence
        for msg in latest_messages:
            eval_segment.add_message(msg)

        # Use parent class for LLM evaluation
        result = await super()._evaluate_segment(eval_segment, patient_id)

        # Get latest messages for each role
        latest_user = next((msg for msg in reversed(segment.messages) if msg.role == AuthorRole.USER), None)
        latest_orchestrator = next((msg for msg in reversed(segment.messages) if msg.name == "Orchestrator"), None)

        # Add details to results
        for r in result:
            details = {
                "context_summary": context_summary,
                "full_conversation": self.chat_history_to_text(segment),
                "user_message": latest_user.content if latest_user else None,
                "orchestrator_message": latest_orchestrator.content if latest_orchestrator else None,
                "patient_id": patient_id
            }

            r["details"] = details

        return result

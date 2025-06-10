# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import \
    AzureChatPromptExecutionSettings
from semantic_kernel.connectors.ai.open_ai.services.azure_chat_completion import AzureChatCompletion
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.contents.utils.author_role import AuthorRole

from evaluation.utils import chat_history_to_readable_text


class EvaluationMetric(ABC):
    """Base class for all evaluation metrics."""

    def chat_history_to_text(self, chat_history: ChatHistory) -> str:
        """
        Convert chat history to readable text with optional summarization.

        Args:
            chat_history: ChatHistory object containing the conversation

        Returns:
            A formatted string representation of the conversation
        """
        messages = []
        for msg in chat_history.messages:
            if not msg.content:
                continue

            role = msg.role.value.upper()
            if role == AuthorRole.ASSISTANT.value.upper():
                role += f" (agent id: {msg.name})"
            messages.append(f"{role}:\n{msg.content}\n\n---\n\n")

        return "".join(messages)

    def create_context_summary(self, history: ChatHistory) -> dict:
        """Create structured summary focusing on the current turn."""
        return {
            "num_turns": len([m for m in history.messages if m.role == AuthorRole.USER]),
            "agents_involved": self._get_unique_agents(history),
            "conversation_flow": self._summarize_current_turn(history)
        }

    def _get_unique_agents(self, history: ChatHistory) -> list[str]:
        """Get unique agents in conversation."""
        agents = set()
        for msg in history.messages:
            if msg.role == AuthorRole.ASSISTANT and msg.name != "Orchestrator":
                agents.add(msg.name)
        return sorted(list(agents))

    def _summarize_current_turn(self, history: ChatHistory) -> str:
        """Summarize flow of current conversation turn."""
        flow = []
        # Get last user message
        for msg in reversed(history.messages):
            if msg.role == AuthorRole.USER:
                flow.append("USER query")
                break

        # Add subsequent messages
        for msg in history.messages:
            if msg in flow:
                continue
            if msg.name == "Orchestrator":
                flow.append("ORCHESTRATOR response")
            elif msg.role == AuthorRole.ASSISTANT:
                flow.append(f"{msg.name} response")

        return " > ".join(flow)  # Use plain '>' instead of unicode arrow

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of the evaluation metric."""
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """Return the description of what this metric evaluates."""
        raise NotImplementedError

    @abstractmethod
    async def evaluate(self, chat_history: ChatHistory, patient_id: str | None = None) -> list[dict[str, Any]]:
        """
        Evaluate the chat history according to the metric.

        Args:
            chat_history: The full chat history as text

        Returns:
            A dictionary containing at least 'score' and 'explanation' keys
        """
        raise NotImplementedError

    def chat_history_to_text(self, chat_history: ChatHistory) -> str:
        """
        Convert the chat history to a text format.

        Args:
            chat_history: The chat history to convert

        Returns:
            The chat history as a string
        """
        return chat_history_to_readable_text(chat_history)


class AgentEvaluationMetric(EvaluationMetric):
    """
    Base class for metrics that evaluate specific agent responses.

    This class handles splitting the chat history into segments where each segment ends with a message from the
    target agent, preceded by n context messages.
    """

    @staticmethod
    def load_valid_agents(scenario: str = "Orchestrator") -> list[str]:
        """
        Load valid agents from scenario config.

        Args:
            scenario: Name of the scenario folder (defaults to "Orchestrator")

        Returns:
            List of valid agent names
        """
        from pathlib import Path

        import yaml

        # Find config path relative to current file
        current_dir = Path(__file__).parent
        yaml_path = current_dir.parents[2] / "scenarios" / scenario / "config" / "agents.yaml"

        try:
            with open(yaml_path, 'r') as f:
                agents_config = yaml.safe_load(f)
                return [agent['name'] for agent in agents_config
                        if isinstance(agent, dict) and 'name' in agent]

        except Exception as e:
            logging.warning(f"Error loading agents config from {yaml_path}: {str(e)}, using default agents")
            # Fall back to default agents if config can't be loaded
            return ["dataorganizer", "radiology", "patientstatus", "treatment",
                    "summary", "researchagent", "clinicaltrials", "pathology"]

    def __init__(self, agent_name: str, context_window: int = 5):
        """
        Initialize the agent evaluation metric.

        Args:
            agent_name: The name of the agent to evaluate
            context_window: Number of preceding messages to include for context
        """
        self.agent_name = agent_name
        self.context_window = context_window

    async def evaluate(self, chat_history: ChatHistory, patient_id: str | None = None) -> list[dict[str, Any]]:
        """
        Evaluate all instances where the target agent responded in the chat history.

        Args:
            chat_history: The full chat history
            patient_id: Optional patient ID for context

        Returns:
            A list containing evaluation results
        """
        # Split the chat history into segments for this agent
        segments = self._split_chat_history(chat_history)

        if not segments:
            logging.warning(f"No responses found from agent '{self.agent_name}' in the chat history")
            return [
                {
                    "score": -1,
                    "explanation": f"No responses found from agent '{self.agent_name}'",
                }
            ]

        logging.info(f"Evaluating {len(segments)} segments for agent '{self.agent_name}'")

        # Evaluate each segment
        individual_results = []
        for segment in segments:
            results = await self._evaluate_segment(segment, patient_id)
            individual_results += results

        return individual_results

    @abstractmethod
    async def _evaluate_segment(self, segment: ChatHistory, patient_id: str | None = None) -> list[dict[str, Any]]:
        """
        Evaluate a single conversation segment.

        Args:
            segment: A segment of the chat history focusing on one agent response
            patient_id: Optional patient ID for context

        Returns:
            Evaluation result for this segment
        """
        raise NotImplementedError("Subclasses must implement _evaluate_segment method")

    def _split_chat_history(self, chat_history: ChatHistory) -> list[ChatHistory]:
        """
        Split the chat history into segments ending with the target agent's responses.

        Segments have a maximum length of `self.context_window` messages before the
        agent's response, but can be shorter if there are not enough messages in the
        history or since the last target agent message.

        Args:
            chat_history: The full chat history

        Returns:
            A list of chat history segments, each ending with a message from the target agent
        """
        segments = []

        # Ignore messages without content
        messages = [msg for msg in chat_history.messages if msg.content]
        if not messages:
            return segments

        i = 0
        last_target_agent_message_idx = -1
        while i < len(messages):
            msg = messages[i]

            if msg.role == AuthorRole.ASSISTANT and msg.name == self.agent_name:
                # Create a new chat history for this segment
                start_idx = max(last_target_agent_message_idx + 1, i - self.context_window)
                segment = ChatHistory()

                # Add context window and the agent's message to the segment
                for j in range(start_idx, i + 1):
                    segment.add_message(messages[j])

                # Update the last target agent message index
                last_target_agent_message_idx = i

                # Check for consecutive messages from the same agent
                i += 1
                msg = messages[i] if i < len(messages) else None
                while msg and msg.role == AuthorRole.ASSISTANT and msg.name == self.agent_name:
                    segment.add_message(msg)

                    i += 1
                    last_target_agent_message_idx = i

                    msg = messages[i] if i < len(messages) else None

                segments.append(segment)

            i += 1

        return segments

    def _extract_agent_response(self, chat_history: ChatHistory) -> Optional[str]:
        """Extract the target agent's latest response from chat history."""
        for message in reversed(chat_history.messages):
            if (
                message.role == AuthorRole.ASSISTANT
                and message.name == self.agent_name
                and message.content
            ):
                return message.content.strip()
        return None

    def _create_error_result(self, error_message: str) -> list[dict[str, Any]]:
        """Create error result structure."""
        logging.error(f"Metric error: {error_message}")
        return [{
            "score": 0,
            "explanation": f"Error: {error_message}",
            "details": {
                "error": error_message
            }
        }]


class ReferenceBasedMetric(AgentEvaluationMetric):
    """
    Base class for metrics that require reference answers.
    Handles loading and caching reference responses from a directory.
    """

    def __init__(self, agent_name: str, reference_dir_path: str, context_window: int = 5):
        """
        Initialize the reference-based metric.

        Args:
            agent_name: Name of the agent in chat history
            reference_dir_path: Path to directory containing reference files
                Each file should be named according to patient ID with supported formats
            context_window: Number of preceding messages to include for context
        """
        super().__init__(agent_name, context_window)
        self.reference_dir_path = reference_dir_path
        self.references = self._load_references()

    def _load_references(self) -> Dict[str, str]:
        """
        Preload all reference files from the reference directory.

        Returns:
            Dictionary mapping patient IDs to reference responses
        """
        references = {}
        if not os.path.exists(self.reference_dir_path):
            logging.warning(f"Reference directory not found: {self.reference_dir_path}")
            return references

        # List files in reference directory
        for filename in os.listdir(self.reference_dir_path):
            file_path = os.path.join(self.reference_dir_path, filename)
            if not os.path.isfile(file_path) or not filename.endswith('.txt'):
                continue

            reference_key = os.path.splitext(filename)[0]

            try:
                with open(file_path, 'r') as f:
                    references[reference_key] = f.read().strip()
                    logging.info(f"Loaded reference {reference_key} from {filename}")
            except Exception as e:
                logging.error(f"Error reading reference file {filename}: {e}")

        logging.info(f"Preloaded {len(references)} reference responses")
        return references

    def _get_reference_response(self, patient_id: str) -> Optional[str]:
        """Get reference response for a patient ID."""
        return self.references.get(patient_id)


class LLMasJudge(EvaluationMetric):
    """
    Abstract base class for LLM-based evaluation metrics.

    This class handles the common pattern of sending chat history to an LLM
    with a system prompt defining evaluation criteria, and parsing the response
    to extract a rating.
    """

    def __init__(self, evaluation_llm_service: AzureChatCompletion):
        """
        Initialize the LLM-based evaluator.

        Args:
            evaluation_llm_service: The LLM service to use for evaluation
        """
        self.evaluation_llm_service = evaluation_llm_service

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """
        Return the system prompt for the evaluator.
        This should include evaluation criteria and rating scale.
        """
        pass

    @property
    @abstractmethod
    def min_score(self) -> int:
        """Return the minimum possible score for this metric."""
        pass

    @property
    @abstractmethod
    def max_score(self) -> int:
        """Return the maximum possible score for this metric."""
        pass

    @abstractmethod
    def process_rating(self, content: str) -> int:
        """
        Extract the rating from LLM response content.

        Args:
            content: The response content from the LLM

        Returns:
            The extracted numerical rating
        """
        pass

    async def evaluate(self, chat_history: ChatHistory, patient_id: str | None = None) -> list[dict[str, Any]]:
        """
        Evaluate the chat history using the LLM.

        Args:
            chat_history: The full chat history as text
            patient_id: Optional patient ID for context

        Returns:
            Dictionary with score and explanation
        """
        return await self._evaluate_content(chat_history)

    async def _evaluate_content(self, content_to_evaluate: ChatHistory) -> list[dict[str, Any]]:
        """
        Helper method to evaluate content using the LLM.

        Args:
            content_to_evaluate: Chat history to evaluate

        Returns:
            List containing evaluation results with score and explanation
        """
        # Prepare the chat history to send to the LLM
        self_chat_history = ChatHistory()
        self_chat_history.add_system_message(self.system_prompt)

        chat_history_text = self.chat_history_to_text(content_to_evaluate)
        self_chat_history.add_user_message(f"Here is the conversation to evaluate:\n\n{chat_history_text}")

        # Get the evaluation from the LLM
        response = await self.evaluation_llm_service.get_chat_message_content(
            chat_history=self_chat_history,
            settings=AzureChatPromptExecutionSettings()
        )

        content = response.content

        # Extract the score using the subclass implementation
        try:
            score = self.process_rating(content)
        except Exception as e:
            logging.warning(f"Error extracting score: {e}. Using default extraction method.")
            score = self.default_rating_extraction(content)

        return [{
            "score": score,
            "explanation": content
        }]

    def default_rating_extraction(self, content: str) -> int:
        """
        Default implementation to extract a rating from LLM response.

        Args:
            content: The response content from the LLM

        Returns:
            The extracted numerical rating or 0 if extraction fails
        """
        # Try to extract rating from the first line
        try:
            first_line = content.split('\n')[0].strip()
            if first_line.startswith("Rating:"):
                rating_text = first_line.replace("Rating:", "").strip()
                score = int(rating_text[0])
                if self.min_score <= score <= self.max_score:
                    return score
        except:
            pass

        # Fall back to regex pattern for "Rating: X"
        match = re.search(r"Rating:\s*([0-9]+)", content)
        if match:
            score = int(match.group(1))
            if self.min_score <= score <= self.max_score:
                return score

        # Look for any digit within the allowed range
        score_pattern = r'\b([' + str(self.min_score) + '-' + str(self.max_score) + r'])\b'
        numbers = re.findall(score_pattern, content)
        if numbers:
            return int(numbers[0])

        # Default if extraction fails
        logging.warning(f"Could not extract evaluation score for {self.name}, defaulting to -1.")
        return -1


class AgentLLMasJudge(AgentEvaluationMetric, LLMasJudge):
    """
    Base class for metrics that use an LLM to evaluate specific agent responses.
    """

    def __init__(self, evaluation_llm_service: AzureChatCompletion, agent_name: str, context_window: int = 5):
        """
        Initialize the agent LLM-based evaluator.

        Args:
            evaluation_llm_service: The LLM service to use for evaluation
            agent_name: The name of the agent to evaluate
            context_window: Number of preceding messages to include for context
        """
        AgentEvaluationMetric.__init__(self, agent_name, context_window)
        LLMasJudge.__init__(self, evaluation_llm_service)

    async def _evaluate_segment(self, segment: ChatHistory, patient_id: str | None = None) -> list[dict[str, Any]]:
        """
        Evaluate a single conversation segment using the LLM.

        Args:
            segment: A segment of the chat history focusing on one agent response
            patient_id: Optional patient ID for context

        Returns:
            Evaluation result for this segment
        """
        # Reuse the evaluation logic from the parent class
        eval_result = await self._evaluate_content(segment)

        for result in eval_result:
            # Include the patient ID in the result
            result["details"] = {
                "patient_id": patient_id,
                "agent_response": self._extract_agent_response(segment),
            }

        return eval_result


class AgentReferenceBasedLLMasJudge(AgentLLMasJudge, ReferenceBasedMetric):
    """
    Evaluation metric that uses an LLM to judge agent responses against reference answers.
    """

    def __init__(self, evaluation_llm_service: AzureChatCompletion, agent_name: str,
                 reference_dir_path: str, context_window: int = 5):
        """
        Initialize the agent reference-based evaluation metric.

        Args:
            evaluation_llm_service: The LLM service to use for evaluation
            agent_name: The name of the agent to evaluate
            reference_dir_path: Path to directory containing reference files
            context_window: Number of preceding messages to include for context
        """
        # Initialize both parent classes
        AgentLLMasJudge.__init__(self, evaluation_llm_service, agent_name, context_window)
        ReferenceBasedMetric.__init__(self, agent_name, reference_dir_path, context_window)

    async def evaluate(self, chat_history: ChatHistory, patient_id: str | None = None) -> list[dict[str, Any]]:
        """
        Evaluate agent responses against reference answers.

        Args:
            chat_history: The chat history to evaluate
            patient_id: The ID of the patient to retrieve reference answer for

        Returns:
            List of evaluation results
        """
        if not patient_id:
            return self._create_error_result("Patient ID is required for reference-based evaluation")

        reference = self._get_reference_response(patient_id)
        if not reference:
            return self._create_error_result(f"No reference found for patient ID: {patient_id}")

        # Store reference for use in _evaluate_segment
        self._current_reference = reference
        self._current_patient_id = patient_id

        # Use the AgentEvaluationMetric method to evaluate segments
        return await AgentEvaluationMetric.evaluate(self, chat_history, patient_id)

    async def _evaluate_segment(self, segment: ChatHistory, patient_id: str | None = None) -> list[dict[str, Any]]:
        """
        Evaluate a single conversation segment against the reference answer.

        Args:
            segment: A segment of the chat history focusing on one agent response
            patient_id: The ID of the patient

        Returns:
            Evaluation result for this segment
        """
        # Prepare the chat history to send to the LLM
        eval_chat_history = ChatHistory()
        eval_chat_history.add_system_message(self.system_prompt)

        chat_segment_text = self.chat_history_to_text(segment)

        # Include both the segment and the reference in the message to the LLM
        eval_chat_history.add_user_message(
            f"Here is the conversation segment to evaluate:\n\n{chat_segment_text}\n\n"
            f"Reference answer for patient {self._current_patient_id}:\n\n{self._current_reference}\n\n"
            f"Compare the agent's response to the reference answer and provide a rating."
        )

        # Get the evaluation from the LLM
        response = await self.evaluation_llm_service.get_chat_message_content(
            chat_history=eval_chat_history,
            settings=AzureChatPromptExecutionSettings()
        )

        content = response.content

        # Extract the score
        try:
            score = self.process_rating(content)
        except Exception as e:
            logging.warning(f"Error extracting score: {e}. Using default extraction method.")
            score = self.default_rating_extraction(content)

        # Include the reference and patient ID in the results
        return [{
            "score": score,
            "explanation": content,
            "details": {
                "patient_id": self._current_patient_id,
                "reference": self._current_reference,
                "agent_response": self._extract_agent_response(segment),
            }
        }]

import json
import logging
import os
import time
from typing import Optional, Literal

from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai.services.azure_chat_completion import AzureChatCompletion
from semantic_kernel.connectors.ai.prompt_execution_settings import PromptExecutionSettings
from semantic_kernel.contents import ChatHistory

logger = logging.getLogger(__name__)

AnalyzerAction = Literal["NONE", "CLEAR", "ACTIVATE_NEW", "SWITCH_EXISTING", "UNCHANGED"]


class PatientContextAnalyzer:
    """
    Single LLM call decides patient context action and (if relevant) patient_id.
    """

    def __init__(
        self,
        deployment_name: Optional[str] = None,
        token_provider=None,
        api_version: Optional[str] = None,
    ):
        self.deployment_name = (
            deployment_name
            or os.getenv("PATIENT_CONTEXT_DECIDER_DEPLOYMENT_NAME")
            or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        )
        if not self.deployment_name:
            raise ValueError("No deployment name for patient context analyzer.")
        self.api_version = api_version or os.getenv("AZURE_OPENAI_API_VERSION") or "2024-10-21"

        logger.info(f"PatientContextAnalyzer initialized with deployment: {self.deployment_name}")

        self._kernel = Kernel()
        self._kernel.add_service(
            AzureChatCompletion(
                service_id="default",
                deployment_name=self.deployment_name,
                api_version=self.api_version,
                ad_token_provider=token_provider,
            )
        )

    async def analyze(
        self, user_text: str, prior_patient_id: Optional[str], known_patient_ids: list[str]
    ) -> tuple[AnalyzerAction, Optional[str], float]:
        start_time = time.time()

        logger.debug(f"Analyzing user input for patient context | Prior: {prior_patient_id}")

        if not user_text or not user_text.strip():
            duration = time.time() - start_time
            logger.debug(f"Empty input received | Duration: {duration:.4f}s")
            return "NONE", None, duration

        # Existing system prompt and LLM call logic...
        system_prompt = f"""
You are a patient context analyzer for healthcare conversations.

TASK: Analyze user input and decide the appropriate patient context action.

ACTIONS:
- NONE: No patient context needed (general questions, greetings, system commands)
- CLEAR: User wants to clear/reset patient context
- ACTIVATE_NEW: User mentions a new patient ID not in known_patient_ids
- SWITCH_EXISTING: User wants to switch to a different known patient
- UNCHANGED: Continue with current patient context

CURRENT STATE:
- Prior patient ID: {prior_patient_id}
- Known patient IDs: {known_patient_ids}

RULES:
1. Extract patient_id ONLY if action is ACTIVATE_NEW or SWITCH_EXISTING
2. Patient IDs are typically "patient_X" format or explicit medical record numbers
3. For CLEAR/NONE/UNCHANGED, set patient_id to null
4. Prioritize explicit patient mentions over implicit context

RESPONSE FORMAT (JSON only):
{{"action": "ACTION_NAME", "patient_id": "extracted_id_or_null", "reasoning": "brief_explanation"}}

USER INPUT: {user_text}
"""

        try:
            chat_history = ChatHistory()
            chat_history.add_system_message(system_prompt)
            chat_history.add_user_message(user_text)

            svc = self._kernel.get_service("default")
            llm_start = time.time()

            results = await svc.get_chat_message_contents(
                chat_history=chat_history,
                settings=PromptExecutionSettings(
                    max_tokens=150,
                    temperature=0.1,
                    response_format={"type": "json_object"}
                ),
            )

            llm_duration = time.time() - llm_start

            if not results:
                raise ValueError("No LLM response received")

            content = results[0].content
            if not content:
                logger.warning("Empty LLM response content")
                duration = time.time() - start_time
                return "NONE", None, duration

            try:
                parsed = json.loads(content)
                action = parsed.get("action", "NONE")
                pid = parsed.get("patient_id")

                # Validation
                valid_actions = ["NONE", "CLEAR", "ACTIVATE_NEW", "SWITCH_EXISTING", "UNCHANGED"]
                if action not in valid_actions:
                    logger.error(f"Invalid action from LLM: {action}")
                    action = "NONE"
                    pid = None

                duration = time.time() - start_time
                logger.info(
                    f"Patient context analysis complete | Action: {action} | Patient: {pid} | Duration: {duration:.4f}s")
                return action, pid, duration

            except json.JSONDecodeError as je:
                logger.error(f"Failed to parse LLM JSON response: {je}")
                duration = time.time() - start_time
                return "NONE", None, duration

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Patient context analysis failed: {e} | Duration: {duration:.4f}s")
            return "NONE", None, duration

    async def summarize_text(self, text: str, patient_id: str) -> str:
        """Generate a patient-specific summary of conversation text."""
        try:
            system_prompt = f"""
You are a clinical summarization assistant. Your ONLY task is to summarize the provided text for patient '{patient_id}'.

**CRITICAL RULES:**
1.  **FOCUS EXCLUSIVELY ON `{patient_id}`**: Ignore all information, notes, or mentions related to any other patient.
2.  **DO NOT BLEND PATIENTS**: If the text mentions other patients (e.g., 'patient_4', 'patient_12'), you must NOT include them in the summary.
3.  **BE CONCISE**: Create a short, bulleted list of 3-5 key points.
4.  **NO FABRICATION**: If there is no relevant information for `{patient_id}` in the text, respond with "No specific information was discussed for patient {patient_id} in this segment."

Summarize the following text:
---
{text}
"""

            chat_history = ChatHistory()
            chat_history.add_system_message(system_prompt)
            chat_history.add_user_message("Please summarize this conversation.")

            svc = self._kernel.get_service("default")
            results = await svc.get_chat_message_contents(
                chat_history=chat_history,
                settings=PromptExecutionSettings(max_tokens=300, temperature=0.3),
            )

            return results[0].content if results and results[0].content else f"Summary unavailable for {patient_id}"

        except Exception as e:
            logger.warning(f"Failed to generate summary: {e}")
            return f"Summary generation failed for {patient_id}"

    # Add this method to the PatientContextAnalyzer class

    def reset_kernel(self):
        """Reset the kernel and service instance to prevent LLM state contamination between patients."""
        try:
            if hasattr(self, '_kernel') and self._kernel:
                # Store current configuration
                current_deployment = self.deployment_name
                current_api_version = self.api_version

                # Create fresh kernel instance
                self._kernel = Kernel()

                # Re-add the service with same configuration
                self._kernel.add_service(
                    AzureChatCompletion(
                        service_id="default",
                        deployment_name=current_deployment,
                        api_version=current_api_version,
                        ad_token_provider=None,  # Adjust if you use token provider
                    )
                )

                logger.info("Kernel reset to prevent patient context contamination")

        except Exception as e:
            logger.warning(f"Error during kernel reset: {e}")

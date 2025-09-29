# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging
import os
import time
from typing import Optional, Literal, Tuple

from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai.services.azure_chat_completion import AzureChatCompletion
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import (
    AzureChatPromptExecutionSettings,
)
from semantic_kernel.contents import ChatHistory
from semantic_kernel.functions import kernel_function

from data_models.patient_context_models import PatientContextDecision

logger = logging.getLogger(__name__)

AnalyzerAction = Literal["NONE", "CLEAR", "ACTIVATE_NEW", "SWITCH_EXISTING", "UNCHANGED"]


class PatientContextAnalyzer:
    """
    Patient context analyzer using Semantic Kernel structured output with JSON schema.
    Follows Microsoft best practices for structured LLM outputs.
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
        self._token_provider = token_provider

        logger.info(f"PatientContextAnalyzer initialized with deployment: {self.deployment_name}")

        self._kernel = Kernel()
        self._kernel.add_service(
            AzureChatCompletion(
                service_id="patient_context_analyzer",
                deployment_name=self.deployment_name,
                api_version=self.api_version,
                ad_token_provider=token_provider,
            )
        )

    @kernel_function(
        description="Analyze user input for patient context decisions",
        name="analyze_patient_context",
    )
    async def analyze_decision(
        self,
        user_text: str,
        prior_patient_id: Optional[str] = None,
        known_patient_ids: Optional[list[str]] = None,
    ) -> PatientContextDecision:
        """
        Analyze user input and return structured patient context decision.

        Args:
            user_text: The user's input message
            prior_patient_id: Current active patient ID (if any)
            known_patient_ids: List of known patient IDs in this session

        Returns:
            PatientContextDecision: Structured decision with action, patient_id, and reasoning
        """
        if known_patient_ids is None:
            known_patient_ids = []

        if not user_text or not user_text.strip():
            return PatientContextDecision(
                action="NONE",
                patient_id=None,
                reasoning="Empty or whitespace user input; no action needed."
            )

        system_prompt = f"""You are a patient context analyzer for healthcare conversations.

TASK: Analyze user input and decide the appropriate patient context action.

AVAILABLE ACTIONS:
- NONE: No patient context needed (general questions, greetings, system commands)
- CLEAR: User wants to clear/reset all patient context
- ACTIVATE_NEW: User mentions a new patient ID not in the known patient list
- SWITCH_EXISTING: User wants to switch to a different known patient
- UNCHANGED: Continue with current patient context

CURRENT STATE:
- Active patient ID: {prior_patient_id or "None"}
- Known patient IDs: {known_patient_ids}

ANALYSIS RULES:
1. Extract patient_id ONLY if action is ACTIVATE_NEW or SWITCH_EXISTING
2. Patient IDs typically follow "patient_X" format or are explicit medical record numbers
3. For CLEAR/NONE/UNCHANGED actions, set patient_id to null
4. Prioritize explicit patient mentions over implicit context
5. Keep reasoning brief and specific (max 50 words)

Respond with a structured JSON object matching the required schema."""

        try:
            chat_history = ChatHistory()
            chat_history.add_system_message(system_prompt)
            chat_history.add_user_message(f"User input: {user_text}")

            # Use AzureChatPromptExecutionSettings with response_format for structured output
            execution_settings = AzureChatPromptExecutionSettings(
                service_id="patient_context_analyzer",
                max_tokens=200,
                temperature=0.1,
                response_format=PatientContextDecision,  # This generates the JSON schema automatically
            )

            svc = self._kernel.get_service("patient_context_analyzer")

            results = await svc.get_chat_message_contents(
                chat_history=chat_history,
                settings=execution_settings,
            )

            if not results or not results[0].content:
                logger.warning("No response from patient context analyzer")
                return PatientContextDecision(
                    action="NONE",
                    patient_id=None,
                    reasoning="No response from analyzer; defaulting to NONE."
                )

            # Parse the structured response
            content = results[0].content

            # Handle both string and already-parsed responses
            if isinstance(content, str):
                try:
                    decision = PatientContextDecision.model_validate_json(content)
                except Exception as e:
                    logger.error(f"Failed to parse structured response: {e}")
                    return PatientContextDecision(
                        action="NONE",
                        patient_id=None,
                        reasoning=f"Parse error: {str(e)[:30]}..."
                    )
            elif isinstance(content, dict):
                try:
                    decision = PatientContextDecision.model_validate(content)
                except Exception as e:
                    logger.error(f"Failed to validate structured response: {e}")
                    return PatientContextDecision(
                        action="NONE",
                        patient_id=None,
                        reasoning=f"Validation error: {str(e)[:30]}..."
                    )
            else:
                logger.warning(f"Unexpected response type: {type(content)}")
                return PatientContextDecision(
                    action="NONE",
                    patient_id=None,
                    reasoning="Unexpected response format; defaulting to NONE."
                )

            logger.info(
                f"Patient context decision: {decision.action} | "
                f"Patient: {decision.patient_id} | "
                f"Reasoning: {decision.reasoning}"
            )

            return decision

        except Exception as e:
            logger.error(f"Patient context analysis failed: {e}")
            return PatientContextDecision(
                action="NONE",
                patient_id=None,
                reasoning=f"Analysis error: {str(e)[:30]}..."
            )

    # Wrapper for backward compatibility - returns timing info
    async def analyze_with_timing(
        self,
        user_text: str,
        prior_patient_id: Optional[str],
        known_patient_ids: list[str],
    ) -> Tuple[PatientContextDecision, float]:
        """
        Analyze with timing information for backward compatibility.
        """
        start_time = time.time()

        decision = await self.analyze_decision(
            user_text=user_text,
            prior_patient_id=prior_patient_id,
            known_patient_ids=known_patient_ids,
        )

        duration = time.time() - start_time
        return decision, duration

    # Legacy wrapper (for existing callers)
    async def analyze(
        self,
        user_text: str,
        prior_patient_id: Optional[str],
        known_patient_ids: list[str],
    ) -> tuple[AnalyzerAction, Optional[str], float]:
        """Legacy wrapper - use analyze_decision() for new code."""
        decision, duration = await self.analyze_with_timing(
            user_text, prior_patient_id, known_patient_ids
        )
        return decision.action, decision.patient_id, duration

    def reset_kernel(self):
        """Reset the kernel and service instance to prevent LLM state contamination between patients."""
        try:
            if hasattr(self, "_kernel") and self._kernel:
                current_deployment = self.deployment_name
                current_api_version = self.api_version
                token_provider = self._token_provider

                self._kernel = Kernel()
                self._kernel.add_service(
                    AzureChatCompletion(
                        service_id="patient_context_analyzer",
                        deployment_name=current_deployment,
                        api_version=current_api_version,
                        ad_token_provider=token_provider,
                    )
                )

                logger.info("Kernel reset completed for patient context isolation")
        except Exception as e:
            logger.warning(f"Error during kernel reset: {e}")

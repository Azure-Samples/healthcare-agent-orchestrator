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

        logger.info(f"🔧 ANALYZER INIT - Deployment: {self.deployment_name} | API Version: {self.api_version}")

        self._kernel = Kernel()
        self._kernel.add_service(
            AzureChatCompletion(
                service_id="default",
                deployment_name=self.deployment_name,
                api_version=self.api_version,
                ad_token_provider=token_provider,
            )
        )
        logger.info(f"🔧 ANALYZER INIT COMPLETE - Kernel and service configured")

    async def analyze(
        self,
        user_text: str,
        prior_patient_id: Optional[str],
        known_patient_ids: list[str],
    ) -> tuple[AnalyzerAction, Optional[str], float]:
        """
        Returns (action, patient_id, duration_sec)
        patient_id is only non-null for ACTIVATE_NEW | SWITCH_EXISTING | UNCHANGED
        """
        start_time = time.time()
        logger.info(f"🔍 ANALYZER START - Input: '{user_text}' | Prior: {prior_patient_id} | Known: {known_patient_ids}")

        if not user_text:
            duration = time.time() - start_time
            logger.info(f"🔍 ANALYZER RESULT - Empty input | Action: NONE | Duration: {duration:.4f}s")
            return "NONE", None, duration

        system_prompt = f"""
You manage patient context for a medical chat application.

Inputs:
- prior_patient_id: {prior_patient_id if prior_patient_id else "null"}
- known_patient_ids: {known_patient_ids}

Rules:
1. If user clearly asks to clear/reset/remove the patient context -> action "CLEAR", patient_id null.
2. If user mentions a patient ID anywhere in their message:
   - Extract the most specific patient identifier (e.g., "patient_4", "patient_123", etc.)
   - If identical to prior_patient_id -> "UNCHANGED"
   - If in known_patient_ids and different -> "SWITCH_EXISTING"
   - If not in known_patient_ids -> "ACTIVATE_NEW"
3. Normalize variants like "patient 6" or "patient id patient_6" to "patient_6". Be tolerant of typos like "patiend id".
4. Ignore vague references without an ID.
5. Output STRICT JSON ONLY. No extra text, no code fences:
{{
  "action": "<ONE OF: NONE | CLEAR | ACTIVATE_NEW | SWITCH_EXISTING | UNCHANGED>",
  "patient_id": "<extracted_id_or_null>"
}}

Examples:
- "switch to patient id patient_5" -> {{"action": "ACTIVATE_NEW", "patient_id": "patient_5"}}
- "switch to patient with patient id patient_4" -> {{"action": "ACTIVATE_NEW", "patient_id": "patient_4"}}
- "switch to patient 6" -> {{"action": "ACTIVATE_NEW", "patient_id": "patient_6"}}
- "clear patient context" -> {{"action": "CLEAR", "patient_id": null}}
""".strip()

        # Build chat history per current SK API
        chat = ChatHistory()
        # chat.add_message(AuthorRole.SYSTEM, system_prompt)
        # chat.add_message(AuthorRole.USER, user_text)

        chat.add_system_message(system_prompt)
        chat.add_user_message(user_text)

        logger.info(f"🔍 ANALYZER LLM CALL - Using chat_history with system prompt length: {len(system_prompt)}")

        try:
            svc = self._kernel.get_service("default")
            logger.info(f"🔍 ANALYZER LLM CALL - Service retrieved: {type(svc).__name__}")

            settings = PromptExecutionSettings(
                service_id="default",
                temperature=0.0,
                top_p=0.0,
                max_tokens=200,
                # If model supports it, enforce JSON mode:
                response_format={"type": "json_object"},
            )

            llm_start = time.time()
            result = await svc.get_chat_message_content(chat_history=chat, settings=settings)
            llm_duration = time.time() - llm_start
            logger.info(f"🔍 ANALYZER LLM CALL COMPLETE - LLM call took: {llm_duration:.4f}s")

            # Normalize result to a single string
            if isinstance(result, list):
                content = "".join([(getattr(c, "content", "") or "") for c in result])
            else:
                content = getattr(result, "content", "") or ""

            content = content.strip()
            logger.info(f"🔍 ANALYZER LLM RESPONSE - Raw content: '{content}'")

            if not content:
                duration = time.time() - start_time
                logger.warning("🔍 ANALYZER LLM RESPONSE - Empty content")
                return "NONE", None, duration

            # Strip accidental code fences
            if content.startswith("```"):
                content = content.strip("`")
                if "\n" in content:
                    content = content.split("\n", 1)[1].strip()

            try:
                data = json.loads(content)
            except json.JSONDecodeError as je:
                duration = time.time() - start_time
                logger.error(f"🔍 ANALYZER JSON ERROR - Failed to parse JSON: {je} | Content: '{content}'")
                return "NONE", None, duration

            action = (data.get("action") or "").strip().upper()
            pid = data.get("patient_id")
            if pid is not None:
                pid = str(pid).strip()

            if action not in {"NONE", "CLEAR", "ACTIVATE_NEW", "SWITCH_EXISTING", "UNCHANGED"}:
                duration = time.time() - start_time
                logger.error(f"🔍 ANALYZER VALIDATION ERROR - Invalid action: {action}")
                return "NONE", None, duration

            duration = time.time() - start_time
            logger.info(f"🔍 ANALYZER RESULT SUCCESS - Action: {action} | Patient ID: {pid} | Duration: {duration:.4f}s")
            return action, pid, duration

        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"🔍 ANALYZER ERROR - Exception: {type(e).__name__}: {e} | Duration: {duration:.4f}s", exc_info=True)
            return "NONE", None, duration

        # Add this method to the PatientContextAnalyzer class (around line 100)

    async def summarize_text(self, text: str, max_tokens: int = 200) -> str:
        """
        Summarize the given chat text into a few concise bullets focused on patient context.
        Returns a short plain-text summary.
        """
        system_prompt = (
            "Summarize the following patient-specific conversation in 3-6 crisp bullets. "
            "Focus ONLY on the current active patient (ignore any references to other patients). "
            "Include: patient ID mentioned, key medical requests, agent actions completed, and immediate next steps. "
            "Be specific and avoid generic phrases. Keep under 80 words total. "
            "If multiple patients are mentioned, focus only on the most recent/active patient."
        )
        chat = ChatHistory()
        chat.add_system_message(system_prompt)
        chat.add_user_message(text[:8000])  # cap input for safety

        try:
            svc = self._kernel.get_service("default")
            settings = PromptExecutionSettings(
                service_id="default",
                temperature=0.0,
                top_p=0.0,
                max_tokens=max_tokens,
            )
            result = await svc.get_chat_message_content(chat_history=chat, settings=settings)
            content = getattr(result, "content", "") or ""
            return content.strip()
        except Exception as e:
            logger.warning(f"🔍 ANALYZER SUMMARY ERROR - {e}")
            return ""

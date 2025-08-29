import json
import logging
import time
from typing import Literal, TypedDict

from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.contents import AuthorRole

from data_models.chat_context import ChatContext, PatientContext
from services.patient_context_analyzer import PatientContextAnalyzer

logger = logging.getLogger(__name__)

PATIENT_CONTEXT_PREFIX = "PATIENT_CONTEXT_JSON:"
Decision = Literal["NONE", "UNCHANGED", "NEW_BLANK", "SWITCH_EXISTING", "CLEAR"]


class TimingInfo(TypedDict):
    analyzer: float
    service: float


class PatientContextService:
    """
    LLM-only patient context manager.
    Decides action + (optionally) patient_id via PatientContextAnalyzer,
    maintains a single system message carrying current patient context JSON.
    """

    def _estimate_tokens(self, text: str) -> int:
        """Rough estimate (~4 chars/token) to avoid new dependencies"""
        return max(1, len(text) // 4)

    def __init__(self, analyzer: PatientContextAnalyzer):
        self.analyzer = analyzer
        logger.info(f"PatientContextService initialized")

    async def decide_and_apply(self, user_text: str, chat_ctx: ChatContext) -> tuple[Decision, TimingInfo]:
        service_start_time = time.time()

        logger.info(f"Patient context decision for '{user_text}' | Current patient: {chat_ctx.patient_id}")

        action, pid, analyzer_duration = await self.analyzer.analyze(
            user_text=user_text,
            prior_patient_id=chat_ctx.patient_id,
            known_patient_ids=list(chat_ctx.patient_contexts.keys()),
        )

        logger.info(f"Analyzer result: {action} | Patient ID: {pid}")

        # Store original state for comparison
        original_patient_id = chat_ctx.patient_id

        decision: Decision = "NONE"
        if action == "CLEAR":
            self._clear(chat_ctx)
            decision = "CLEAR"
        elif action in ("ACTIVATE_NEW", "SWITCH_EXISTING"):
            decision = self._activate_patient(pid, chat_ctx) if pid else "NONE"
        elif action == "UNCHANGED":
            decision = "UNCHANGED"

        # Log state changes only if they occurred
        if original_patient_id != chat_ctx.patient_id:
            logger.info(f"Patient context changed: '{original_patient_id}' -> '{chat_ctx.patient_id}'")

        service_duration = time.time() - service_start_time
        timing: TimingInfo = {"analyzer": round(analyzer_duration, 4), "service": round(service_duration, 4)}

        # Generate patient-specific LLM-based chat summary
        chat_summary = None
        if chat_ctx.patient_id:
            # Find messages since the last patient context switch to current patient
            patient_specific_messages = []

            # Go through messages in reverse to find current patient's conversation segment
            for message in reversed(chat_ctx.chat_history.messages):
                # Check if this is a system message with patient context JSON
                if (message.role == AuthorRole.SYSTEM and
                    isinstance(message.content, str) and
                        message.content.startswith(PATIENT_CONTEXT_PREFIX)):
                    try:
                        json_content = message.content[len(PATIENT_CONTEXT_PREFIX):].strip()
                        payload = json.loads(json_content)
                        message_patient_id = payload.get("patient_id")

                        # If we find a context message for a *different* patient,
                        # that's the boundary of the current patient's conversation.
                        if message_patient_id != chat_ctx.patient_id:
                            break
                    except Exception as e:
                        logger.warning(f"Failed to parse system message JSON: {e}")
                        continue

                patient_specific_messages.append(message)

            # Create summary from patient-specific messages only
            if patient_specific_messages:
                patient_specific_messages.reverse()  # Back to chronological order
                history_text = "\n".join(
                    str(getattr(m, "role", "")) + ": " + (m.content if isinstance(m.content, str) else str(m.content or ""))
                    for m in patient_specific_messages
                    if not (m.role == AuthorRole.SYSTEM and isinstance(m.content, str) and m.content.startswith(PATIENT_CONTEXT_PREFIX))
                )[:8000]

                if history_text.strip():
                    try:
                        # LLM still does the summarization, but with patient-specific input
                        chat_summary = await self.analyzer.summarize_text(history_text, chat_ctx.patient_id)
                        logger.debug(f"Generated summary for {chat_ctx.patient_id}")
                    except Exception as e:
                        logger.warning(f"Failed to summarize: {e}")
                        chat_summary = f"Chat summary for {chat_ctx.patient_id} unavailable"

        token_counts = {
            "history_estimate": self._estimate_tokens(chat_summary) if chat_summary else 0,
            "summary_estimate": self._estimate_tokens(chat_summary) if chat_summary else 0,
        }

        if decision == "CLEAR":
            self._remove_system_message(chat_ctx)
        else:
            self._ensure_system_message(chat_ctx, timing, chat_summary, token_counts)

        logger.info(f"Patient context decision complete: {decision} | Patient: {chat_ctx.patient_id}")
        return decision, timing

    # -------- Internal helpers --------

    def _activate_patient(self, patient_id: str, chat_ctx: ChatContext) -> Decision:
        if not patient_id:
            return "NONE"

        # Same patient
        if patient_id == chat_ctx.patient_id:
            return "UNCHANGED"

        # Switch to existing
        if patient_id in chat_ctx.patient_contexts:
            chat_ctx.patient_id = patient_id
            logger.info(f"Switched to existing patient: {patient_id}")
            return "SWITCH_EXISTING"

        # New blank patient context
        chat_ctx.patient_contexts[patient_id] = PatientContext(patient_id=patient_id)
        chat_ctx.patient_id = patient_id
        logger.info(f"Created new patient context: {patient_id}")
        return "NEW_BLANK"

    def _clear(self, chat_ctx: ChatContext):
        logger.info(f"Clearing patient context: {chat_ctx.patient_id}")
        chat_ctx.patient_id = None  # retain historical contexts for potential reuse

    def _remove_system_message(self, chat_ctx: ChatContext):
        """
        Removes only the system message(s) for the *currently active* patient.
        This preserves the system messages from other patients, which act as crucial
        boundaries for the conversation history slicing logic.
        """
        if not chat_ctx.patient_id:
            # If there's no active patient, there's nothing to remove.
            return

        current_patient_id = chat_ctx.patient_id
        messages_to_keep = []
        removed_count = 0

        for m in chat_ctx.chat_history.messages:
            if (
                m.role == AuthorRole.SYSTEM
                and isinstance(m.content, str)
                and m.content.startswith(PATIENT_CONTEXT_PREFIX)
            ):
                try:
                    # Extract patient_id from the message payload
                    json_content = m.content[len(PATIENT_CONTEXT_PREFIX):].strip()
                    payload = json.loads(json_content)
                    message_patient_id = payload.get("patient_id")

                    # If the message is for the current patient, we skip it (i.e., remove it)
                    if message_patient_id == current_patient_id:
                        removed_count += 1
                        continue
                except (json.JSONDecodeError, KeyError):
                    # If parsing fails, keep the message to be safe
                    pass

            # Keep all other messages
            messages_to_keep.append(m)

        if removed_count > 0:
            logger.debug(
                f"Removed {removed_count} prior context system message(s) for current patient '{current_patient_id}'.")

        chat_ctx.chat_history.messages = messages_to_keep

    def _ensure_system_message(self, chat_ctx: ChatContext, timing: TimingInfo,
                               chat_summary: str | None = None,
                               token_counts: dict | None = None):
        self._remove_system_message(chat_ctx)

        if not chat_ctx.patient_id:
            return

        # Simplified payload without agent tracking and chat excerpt
        payload = {
            "conversation_id": chat_ctx.conversation_id,
            "patient_id": chat_ctx.patient_id,
            "all_patient_ids": list(chat_ctx.patient_contexts.keys()),
            "timing_sec": timing,
            "chat_summary": chat_summary,
            "token_counts": token_counts or {},
        }

        line = f"{PATIENT_CONTEXT_PREFIX} {json.dumps(payload, separators=(',', ':'))}"

        system_message = ChatMessageContent(role=AuthorRole.SYSTEM, content=line)
        chat_ctx.chat_history.messages.insert(0, system_message)

        logger.debug(f"Added patient context system message for {chat_ctx.patient_id}")

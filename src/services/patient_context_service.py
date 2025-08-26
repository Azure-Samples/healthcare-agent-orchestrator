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
        logger.info(f"🏥 SERVICE INIT - PatientContextService initialized with analyzer: {type(analyzer).__name__}")

    async def decide_and_apply(self, user_text: str, chat_ctx: ChatContext) -> tuple[Decision, TimingInfo]:
        service_start_time = time.time()

        logger.info(f"🏥 SERVICE START - Input: '{user_text}' | Conversation: {chat_ctx.conversation_id}")
        logger.info(
            f"🏥 SERVICE START - Current Patient: {chat_ctx.patient_id} | Known Patients: {list(chat_ctx.patient_contexts.keys())}")
        logger.info(f"🏥 SERVICE START - Chat history messages: {len(chat_ctx.chat_history.messages)}")

        # Log current system messages
        system_messages = [m for m in chat_ctx.chat_history.messages if m.role == AuthorRole.SYSTEM]
        logger.info(f"🏥 SERVICE START - Current system messages: {len(system_messages)}")
        for i, msg in enumerate(system_messages):
            content = getattr(msg, 'content', '')
            if isinstance(content, str) and content.startswith(PATIENT_CONTEXT_PREFIX):
                logger.info(f"🏥 SERVICE START - System message {i}: {content}")

        action, pid, analyzer_duration = await self.analyzer.analyze(
            user_text=user_text,
            prior_patient_id=chat_ctx.patient_id,
            known_patient_ids=list(chat_ctx.patient_contexts.keys()),
        )

        logger.info(
            f"🏥 SERVICE ANALYZER RESULT - Action: {action} | Patient ID: {pid} | Analyzer Duration: {analyzer_duration:.4f}s")

        # Store original state for comparison
        original_patient_id = chat_ctx.patient_id
        original_patient_contexts = dict(chat_ctx.patient_contexts)

        decision: Decision = "NONE"
        if action == "CLEAR":
            logger.info(f"🏥 SERVICE CLEARING - Clearing patient context from: {chat_ctx.patient_id}")
            self._clear(chat_ctx)
            decision = "CLEAR"
            logger.info(f"🏥 SERVICE CLEARED - Patient context cleared, now: {chat_ctx.patient_id}")
        elif action in ("ACTIVATE_NEW", "SWITCH_EXISTING"):
            logger.info(f"🏥 SERVICE ACTIVATING - Attempting to activate patient: {pid}")
            decision = self._activate_patient(pid, chat_ctx) if pid else "NONE"
            logger.info(f"🏥 SERVICE ACTIVATED - Result decision: {decision} | New patient: {chat_ctx.patient_id}")
        elif action == "UNCHANGED":
            logger.info(f"🏥 SERVICE UNCHANGED - Patient context unchanged, keeping: {chat_ctx.patient_id}")
            decision = "UNCHANGED"

        # Log state changes
        if original_patient_id != chat_ctx.patient_id:
            logger.info(
                f"🏥 SERVICE STATE CHANGE - Patient ID changed from '{original_patient_id}' to '{chat_ctx.patient_id}'")

        if original_patient_contexts != chat_ctx.patient_contexts:
            logger.info(
                f"🏥 SERVICE STATE CHANGE - Patient contexts changed from {list(original_patient_contexts.keys())} to {list(chat_ctx.patient_contexts.keys())}")

        service_duration = time.time() - service_start_time
        timing: TimingInfo = {"analyzer": round(analyzer_duration, 4), "service": round(service_duration, 4)}

        # Generate patient-specific LLM-based chat summary
        chat_summary = None
        if chat_ctx.patient_id:
            # Find messages since the last patient context switch to current patient
            patient_specific_messages = []
            found_current_patient_context = False

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

                        if message_patient_id == chat_ctx.patient_id:
                            # Found a system message for current patient, mark the start
                            found_current_patient_context = True
                            continue
                        elif found_current_patient_context and message_patient_id != chat_ctx.patient_id:
                            # Found a system message for a different patient, stop collecting
                            break
                    except Exception as e:
                        logger.warning(f"🏥 SERVICE SUMMARY - Failed to parse system message JSON: {e}")
                        continue
                else:
                    # Regular message - include it if we're in current patient's context
                    if found_current_patient_context:
                        patient_specific_messages.append(message)

            # If no patient context switch found, include recent messages (fallback)
            if not found_current_patient_context:
                logger.info(f"🏥 SERVICE SUMMARY - No patient context switch found, using recent messages")
                patient_specific_messages = list(chat_ctx.chat_history.messages[-10:])  # Last 10 messages

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
                        chat_summary = await self.analyzer.summarize_text(history_text)
                        logger.info(
                            f"🏥 SERVICE SUMMARY - Generated patient-specific summary for {chat_ctx.patient_id}: {len(chat_summary)} chars")
                    except Exception as e:
                        logger.warning(f"🏥 SERVICE SUMMARY - Failed to summarize: {e}")
                        chat_summary = f"Chat summary for {chat_ctx.patient_id} unavailable"
                else:
                    logger.info(f"🏥 SERVICE SUMMARY - No relevant text found for patient {chat_ctx.patient_id}")
                    chat_summary = f"No recent activity for {chat_ctx.patient_id}"
            else:
                logger.info(f"🏥 SERVICE SUMMARY - No messages found for patient {chat_ctx.patient_id}")
                chat_summary = f"New patient context for {chat_ctx.patient_id}"

        token_counts = {
            "history_estimate": self._estimate_tokens(chat_summary) if chat_summary else 0,
            "summary_estimate": self._estimate_tokens(chat_summary) if chat_summary else 0,
        }

        logger.info(f"🏥 SERVICE SYSTEM MESSAGE - Updating system message for decision: {decision}")

        if decision == "CLEAR":
            self._remove_system_message(chat_ctx)
            logger.info(f"🏥 SERVICE SYSTEM MESSAGE - Removed system message for CLEAR decision")
        else:
            self._ensure_system_message(chat_ctx, timing, chat_summary, token_counts)
            logger.info(f"🏥 SERVICE SYSTEM MESSAGE - Ensured system message for patient: {chat_ctx.patient_id}")

        # Log final state
        final_system_messages = [m for m in chat_ctx.chat_history.messages if m.role == AuthorRole.SYSTEM]
        logger.info(f"🏥 SERVICE FINAL - System messages after update: {len(final_system_messages)}")
        for i, msg in enumerate(final_system_messages):
            content = getattr(msg, 'content', '')
            if isinstance(content, str) and content.startswith(PATIENT_CONTEXT_PREFIX):
                logger.info(f"🏥 SERVICE FINAL - System message {i}: {content}")

        logger.info(
            f"🏥 SERVICE COMPLETE - Final Decision: {decision} | Final Patient: {chat_ctx.patient_id} | Timing: {timing}")
        return decision, timing

    # -------- Internal helpers --------

    def _activate_patient(self, patient_id: str, chat_ctx: ChatContext) -> Decision:
        logger.info(
            f"🏥 SERVICE ACTIVATE START - Checking patient_id: '{patient_id}' | Current: '{chat_ctx.patient_id}'")

        if not patient_id:
            logger.info(f"🏥 SERVICE ACTIVATE - No patient ID provided, returning NONE")
            return "NONE"

        # Same patient
        if patient_id == chat_ctx.patient_id:
            logger.info(f"🏥 SERVICE ACTIVATE - Same patient '{patient_id}', returning UNCHANGED")
            return "UNCHANGED"

        # Switch to existing
        if patient_id in chat_ctx.patient_contexts:
            logger.info(f"🏥 SERVICE ACTIVATE - Switching to existing patient: '{patient_id}'")
            chat_ctx.patient_id = patient_id
            logger.info(f"🏥 SERVICE ACTIVATE - Successfully switched to existing patient: '{patient_id}'")
            return "SWITCH_EXISTING"

        # New blank patient context
        logger.info(f"🏥 SERVICE ACTIVATE - Creating new patient context for: '{patient_id}'")
        chat_ctx.patient_contexts[patient_id] = PatientContext(patient_id=patient_id)
        chat_ctx.patient_id = patient_id
        logger.info(f"🏥 SERVICE ACTIVATE - Successfully created new patient context for: '{patient_id}'")
        logger.info(f"🏥 SERVICE ACTIVATE - All patient contexts now: {list(chat_ctx.patient_contexts.keys())}")
        return "NEW_BLANK"

    def _clear(self, chat_ctx: ChatContext):
        logger.info(f"🏥 SERVICE CLEAR - Clearing patient_id from: '{chat_ctx.patient_id}' to None")
        chat_ctx.patient_id = None  # retain historical contexts for potential reuse
        logger.info(
            f"🏥 SERVICE CLEAR - Patient ID cleared, contexts retained: {list(chat_ctx.patient_contexts.keys())}")

    def _remove_system_message(self, chat_ctx: ChatContext):
        original_count = len(chat_ctx.chat_history.messages)
        original_system_count = len([m for m in chat_ctx.chat_history.messages if m.role == AuthorRole.SYSTEM])

        logger.info(
            f"🏥 SERVICE REMOVE MSG START - Total messages: {original_count} | System messages: {original_system_count}")

        # Log what we're about to remove
        to_remove = []
        for i, m in enumerate(chat_ctx.chat_history.messages):
            if (m.role == AuthorRole.SYSTEM and
                isinstance(m.content, str) and
                    m.content.startswith(PATIENT_CONTEXT_PREFIX)):
                to_remove.append((i, m.content))

        logger.info(f"🏥 SERVICE REMOVE MSG - Found {len(to_remove)} PATIENT_CONTEXT messages to remove")
        for i, content in to_remove:
            logger.info(f"🏥 SERVICE REMOVE MSG - Removing message {i}: {content}")

        chat_ctx.chat_history.messages = [
            m
            for m in chat_ctx.chat_history.messages
            if not (
                m.role == AuthorRole.SYSTEM
                and isinstance(m.content, str)
                and m.content.startswith(PATIENT_CONTEXT_PREFIX)
            )
        ]  # type: ignore

        new_count = len(chat_ctx.chat_history.messages)
        new_system_count = len([m for m in chat_ctx.chat_history.messages if m.role == AuthorRole.SYSTEM])
        removed_count = original_count - new_count

        logger.info(
            f"🏥 SERVICE REMOVE MSG COMPLETE - Removed {removed_count} messages | Total: {original_count}->{new_count} | System: {original_system_count}->{new_system_count}")

    def _ensure_system_message(self, chat_ctx: ChatContext, timing: TimingInfo,
                               chat_summary: str | None = None,
                               token_counts: dict | None = None):
        logger.info(
            f"🏥 SERVICE ENSURE MSG START - Patient: '{chat_ctx.patient_id}' | Conversation: '{chat_ctx.conversation_id}'")

        self._remove_system_message(chat_ctx)

        if not chat_ctx.patient_id:
            logger.info(f"🏥 SERVICE ENSURE MSG - No patient ID, not adding system message")
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

        logger.info(f"🏥 SERVICE ENSURE MSG - Creating system message: {line}")

        system_message = ChatMessageContent(role=AuthorRole.SYSTEM, content=line)
        chat_ctx.chat_history.messages.insert(0, system_message)

        total_messages = len(chat_ctx.chat_history.messages)
        system_messages = len([m for m in chat_ctx.chat_history.messages if m.role == AuthorRole.SYSTEM])

        logger.info(
            f"🏥 SERVICE ENSURE MSG COMPLETE - System message added at position 0 | Total messages: {total_messages} | System messages: {system_messages}")

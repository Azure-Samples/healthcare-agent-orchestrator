import json
import logging
import re
import time
from datetime import datetime, timezone  # Add timezone here
from typing import Literal

from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.contents import AuthorRole
from semantic_kernel.contents import TextContent

from data_models.chat_context import ChatContext, PatientContext
from data_models.patient_context_models import TimingInfo, PatientContextSystemMessage
from services.patient_context_analyzer import PatientContextAnalyzer

logger = logging.getLogger(__name__)

PATIENT_CONTEXT_PREFIX = "PATIENT_CONTEXT_JSON"
PATIENT_ID_PATTERN = re.compile(r"^patient_[0-9]+$")
Decision = Literal["NONE", "UNCHANGED", "NEW_BLANK", "SWITCH_EXISTING",
                   "CLEAR", "RESTORED_FROM_STORAGE", "NEEDS_PATIENT_ID"]


class PatientContextService:
    """
    Simplified patient context manager:
    1. Use analyzer to detect explicit patient IDs
    2. Fall back to storage if analyzer returns NONE
    3. Simple file-based patient isolation
    4. Kernel reset on patient switches
    """

    def __init__(self, analyzer: PatientContextAnalyzer, registry_accessor=None, context_accessor=None):
        self.analyzer = analyzer
        self.registry_accessor = registry_accessor
        self.context_accessor = context_accessor
        logger.info(f"PatientContextService initialized with storage fallback: {registry_accessor is not None}")

    async def decide_and_apply(self, user_text: str, chat_ctx: ChatContext) -> tuple[Decision, TimingInfo]:
        service_start_time = time.time()

        # Skip analyzer for very short messages that are likely agent handoffs
        if user_text and len(user_text.strip()) <= 15 and not any(
            word in user_text.lower() for word in ["patient", "clear", "switch"]
        ):
            logger.info(f"Skipping analyzer for short handoff message: '{user_text}'")

            if not chat_ctx.patient_id:
                fallback_start = time.time()
                restored = await self._try_restore_from_storage(chat_ctx)
                fallback_duration = time.time() - fallback_start
                decision = "RESTORED_FROM_STORAGE" if restored else "NONE"
            else:
                fallback_duration = 0.0
                decision = "UNCHANGED"

            timing = TimingInfo(
                analyzer=0.0,
                storage_fallback=fallback_duration,
                service=time.time() - service_start_time,
            )
            return decision, timing

        logger.info(f"Patient context decision for '{user_text}' | Current patient: {chat_ctx.patient_id}")

        # STEP 1: Run the analyzer with structured output
        decision_model, analyzer_duration = await self.analyzer.analyze_with_timing(
            user_text=user_text,
            prior_patient_id=chat_ctx.patient_id,
            known_patient_ids=list(chat_ctx.patient_contexts.keys()),
        )

        action = decision_model.action
        pid = decision_model.patient_id

        logger.info(
            f"Analyzer decision: {action} | Patient ID: {pid} | "
            f"Reasoning: {decision_model.reasoning}"
        )

        # STEP 2: Handle analyzer results
        fallback_duration = 0.0

        if action == "CLEAR":
            await self._archive_all_and_recreate(chat_ctx)
            timing = TimingInfo(
                analyzer=analyzer_duration,
                storage_fallback=0.0,
                service=time.time() - service_start_time,
            )
            return "CLEAR", timing

        elif action in ("ACTIVATE_NEW", "SWITCH_EXISTING"):
            if not pid or not PATIENT_ID_PATTERN.match(pid):
                logger.warning(f"Invalid patient ID from analyzer: {pid}")
                decision = "NEEDS_PATIENT_ID"
            else:
                decision = await self._activate_patient_with_registry(pid, chat_ctx)

        elif action == "NONE":
            fb_start = time.time()
            if not chat_ctx.patient_id:
                restored = await self._try_restore_from_storage(chat_ctx)
                decision = "RESTORED_FROM_STORAGE" if restored else "NONE"
            else:
                decision = "UNCHANGED"
            fallback_duration = time.time() - fb_start

        elif action == "UNCHANGED":
            decision = "UNCHANGED"
        else:
            decision = "NONE"

        service_duration = time.time() - service_start_time
        timing = TimingInfo(
            analyzer=analyzer_duration,
            storage_fallback=fallback_duration,
            service=service_duration,
        )

        if chat_ctx.patient_id:
            await self._ensure_system_message(chat_ctx, timing)

        return decision, timing

    async def set_explicit_patient_context(self, patient_id: str, chat_ctx: ChatContext) -> bool:
        if not patient_id or not PATIENT_ID_PATTERN.match(patient_id):
            logger.warning(f"Invalid patient ID format: {patient_id}")
            return False

        if chat_ctx.patient_id and patient_id != chat_ctx.patient_id:
            logger.info(f"Resetting kernel for explicit patient switch: {chat_ctx.patient_id} -> {patient_id}")
            self.analyzer.reset_kernel()

        restored = await self._try_restore_specific_patient(patient_id, chat_ctx)
        if not restored:
            chat_ctx.patient_contexts[patient_id] = PatientContext(patient_id=patient_id)
            logger.info(f"Created new patient context: {patient_id}")

        chat_ctx.patient_id = patient_id
        timing = TimingInfo(analyzer=0.0, storage_fallback=0.0, service=0.0)
        await self._ensure_system_message(chat_ctx, timing)

        if self.registry_accessor:
            try:
                await self._update_registry_storage(chat_ctx)
            except Exception as e:
                logger.warning(f"Failed to update registry storage: {e}")

        return True

    async def _ensure_system_message(self, chat_ctx: ChatContext, timing: TimingInfo):
        """Ensure system message with patient context data using structured model."""
        self._remove_system_message(chat_ctx)

        if not chat_ctx.patient_id:
            return

        # Get all session patients from registry
        all_patient_ids = list(chat_ctx.patient_contexts.keys())
        if self.registry_accessor:
            try:
                patient_registry, _ = await self.registry_accessor.read_registry(chat_ctx.conversation_id)
                if patient_registry:
                    all_patient_ids = list(patient_registry.keys())
                    logger.debug(f"Using patient registry for system message: {all_patient_ids}")
            except Exception as e:
                logger.warning(f"Failed to read patient registry for system message: {e}")

        # Use structured model for system message
        payload = PatientContextSystemMessage(
            conversation_id=chat_ctx.conversation_id,
            patient_id=chat_ctx.patient_id,
            all_patient_ids=all_patient_ids,
            timing_sec=timing,
        )

        # Fix: Remove separators parameter - Pydantic doesn't support it
        line = f"{PATIENT_CONTEXT_PREFIX}: {payload.model_dump_json()}"
        system_message = ChatMessageContent(
            role=AuthorRole.SYSTEM,
            items=[TextContent(text=line)]
        )
        chat_ctx.chat_history.messages.insert(0, system_message)
        logger.debug(
            f"Added structured patient context system message for {chat_ctx.patient_id} "
            f"with {len(all_patient_ids)} session patients"
        )

    async def _try_restore_from_storage(self, chat_ctx: ChatContext) -> bool:
        """Try to restore patient context from storage files."""
        logger.info(f"Attempting storage fallback for conversation: {chat_ctx.conversation_id}")

        # Priority 1: Check patient registry file (session registry)
        if self.registry_accessor:
            try:
                patient_registry, active_patient_id = await self.registry_accessor.read_registry(chat_ctx.conversation_id)

                if patient_registry and active_patient_id:
                    logger.info(f"Found {len(patient_registry)} patients. Active: {active_patient_id}")

                    # Restore all patient metadata from registry
                    for patient_id, registry_entry in patient_registry.items():
                        chat_ctx.patient_contexts[patient_id] = PatientContext(
                            patient_id=patient_id,
                            facts=registry_entry.get("facts", {})
                        )
                        logger.info(f"Restored patient {patient_id} metadata")

                    # Set active patient and load their isolated chat history
                    if active_patient_id in patient_registry:
                        chat_ctx.patient_id = active_patient_id

                        # Load isolated chat history for active patient
                        if self.context_accessor:
                            try:
                                restored_chat_ctx = await self.context_accessor.read(chat_ctx.conversation_id, active_patient_id)
                                if restored_chat_ctx and hasattr(restored_chat_ctx, 'chat_history'):
                                    # Clear current history and load patient-specific history
                                    chat_ctx.chat_history.messages.clear()
                                    chat_ctx.chat_history.messages.extend(restored_chat_ctx.chat_history.messages)
                                    logger.info(f"Loaded isolated chat history for: {active_patient_id}")
                            except Exception as e:
                                logger.warning(f"Failed to load patient-specific chat history: {e}")

                        logger.info(f"Restored active patient: {active_patient_id}")
                        return True
            except Exception as e:
                logger.warning(f"Failed to read patient registry: {e}")

        # Priority 2: Check session context
        if self.context_accessor:
            try:
                restored_ctx = await self.context_accessor.read(chat_ctx.conversation_id)
                if restored_ctx and restored_ctx.patient_id:
                    chat_ctx.patient_id = restored_ctx.patient_id
                    chat_ctx.patient_contexts = restored_ctx.patient_contexts or {}
                    chat_ctx.chat_history = restored_ctx.chat_history or chat_ctx.chat_history
                    logger.info(f"Restored session context: {restored_ctx.patient_id}")
                    return True
            except Exception as e:
                logger.warning(f"Failed to read session context: {e}")

        logger.info("No patient context found in storage")
        return False

# Replace the incomplete _archive_all_and_recreate method with this complete implementation:

    async def _archive_all_and_recreate(self, chat_ctx: ChatContext) -> None:
        """Archive all files to blob storage and recreate fresh files."""
        logger.info("Archiving all contexts to blob storage for conversation: %s", chat_ctx.conversation_id)

        # Kernel reset for complete context clear
        if chat_ctx.patient_id:
            logger.info("Resetting kernel for complete context clear")
            self.analyzer.reset_kernel()

        archive_failures = []

        # Get ALL patients from registry
        all_patient_ids = list(chat_ctx.patient_contexts.keys())

        # Try to get the complete list from the patient registry
        if self.registry_accessor:
            try:
                patient_registry, _ = await self.registry_accessor.read_registry(chat_ctx.conversation_id)
                if patient_registry:
                    all_patient_ids = list(patient_registry.keys())
                    logger.info("Found %s patients in registry to archive: %s", len(all_patient_ids), all_patient_ids)
                else:
                    logger.warning("No patient registry found for archival")
            except Exception as e:
                logger.warning("Failed to read patient registry for archival: %s", e)

        # Create timestamped archive folder
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
        archive_folder = "archive/%s" % timestamp

        try:
            logger.info("Starting archive to folder: %s", archive_folder)

            # Archive session context (main conversation)
            try:
                await self.context_accessor.archive_to_folder(chat_ctx.conversation_id, None, archive_folder)
                logger.info("Archived session context to %s", archive_folder)
            except Exception as e:
                logger.warning("Failed to archive session context: %s", e)
                archive_failures.append("session")

            # Archive ALL patient contexts from registry
            for patient_id in all_patient_ids:
                try:
                    await self.context_accessor.archive_to_folder(chat_ctx.conversation_id, patient_id, archive_folder)
                    logger.info("Archived patient context for %s to %s", patient_id, archive_folder)
                except Exception as e:
                    logger.warning("Failed to archive patient context for %s: %s", patient_id, e)
                    archive_failures.append(patient_id)

            # Archive patient registry
            if self.registry_accessor:
                try:
                    await self.registry_accessor.archive_registry(chat_ctx.conversation_id)
                    logger.info("Archived patient registry for %s", chat_ctx.conversation_id)
                except Exception as e:
                    logger.warning("Failed to archive patient registry: %s", e)
                    archive_failures.append("registry")

            # Report archive status
            if archive_failures:
                logger.warning("Some archives failed: %s", archive_failures)
            else:
                logger.info("Successfully archived all contexts to %s", archive_folder)

        except Exception as e:
            logger.error("Critical failure during archive process: %s", e)

        # Clear memory only after archival attempt (even if some failed)
        chat_ctx.patient_id = None
        chat_ctx.patient_contexts.clear()
        chat_ctx.chat_history.messages.clear()
        self._remove_system_message(chat_ctx)

        logger.info("Archival complete - memory cleared for fresh start")

    async def _activate_patient_with_registry(self, patient_id: str, chat_ctx: ChatContext) -> Decision:
        """Activate patient and load from registry if available."""
        if not patient_id:
            return "NEEDS_PATIENT_ID"

        # Same patient
        if patient_id == chat_ctx.patient_id:
            return "UNCHANGED"

        # Kernel reset when switching patients
        if chat_ctx.patient_id and patient_id != chat_ctx.patient_id:
            logger.info(f"Resetting kernel for patient switch: {chat_ctx.patient_id} -> {patient_id}")
            self.analyzer.reset_kernel()

        # Load registry metadata for all patients
        if self.registry_accessor:
            try:
                patient_registry, _ = await self.registry_accessor.read_registry(chat_ctx.conversation_id)
                if patient_registry:
                    # Load metadata for all patients from registry
                    for pid, registry_entry in patient_registry.items():
                        if pid not in chat_ctx.patient_contexts:
                            chat_ctx.patient_contexts[pid] = PatientContext(
                                patient_id=pid,
                                facts=registry_entry.get("facts", {})
                            )
            except Exception as e:
                logger.warning(f"Failed to load patient registry: {e}")

        # Check if we have registry data for this patient
        if self.registry_accessor:
            try:
                patient_registry, _ = await self.registry_accessor.read_registry(chat_ctx.conversation_id)
                if patient_id in patient_registry:
                    registry_entry = patient_registry[patient_id]
                    if patient_id not in chat_ctx.patient_contexts:
                        chat_ctx.patient_contexts[patient_id] = PatientContext(
                            patient_id=patient_id,
                            facts=registry_entry.get("facts", {})
                        )

                    chat_ctx.patient_id = patient_id

                    # Load isolated chat history for this patient
                    if self.context_accessor:
                        try:
                            restored_chat_ctx = await self.context_accessor.read(chat_ctx.conversation_id, patient_id)
                            if restored_chat_ctx and hasattr(restored_chat_ctx, 'chat_history'):
                                # Clear current history and load patient-specific history
                                chat_ctx.chat_history.messages.clear()
                                chat_ctx.chat_history.messages.extend(restored_chat_ctx.chat_history.messages)
                                logger.info(f"Loaded isolated chat history for: {patient_id}")
                        except Exception as e:
                            logger.warning(f"Failed to load patient-specific chat history: {e}")

                    logger.info(f"Switched to existing patient from registry: {patient_id}")
                    # CRITICAL: Update registry to mark this patient as currently active
                    await self._update_registry_storage(chat_ctx)

                    return "SWITCH_EXISTING"
            except Exception as e:
                logger.warning(f"Failed to check registry for {patient_id}: {e}")

        # Switch to existing in memory - PRESERVE CHAT HISTORY
        if patient_id in chat_ctx.patient_contexts:
            chat_ctx.patient_id = patient_id
            logger.info(f"Switched to existing patient (preserving chat history): {patient_id}")
            # Update registry when switching to existing patient
            await self._update_registry_storage(chat_ctx)
            return "SWITCH_EXISTING"

        # New blank patient context - PRESERVE CHAT HISTORY
        chat_ctx.patient_contexts[patient_id] = PatientContext(patient_id=patient_id)
        chat_ctx.patient_id = patient_id
        logger.info(f"Created new patient context (preserving chat history): {patient_id}")

        # CRITICAL: Update registry storage for new patient
        await self._update_registry_storage(chat_ctx)

        return "NEW_BLANK"

    async def _update_registry_storage(self, chat_ctx: ChatContext):
        """Update registry storage for current patient."""
        if not self.registry_accessor or not chat_ctx.patient_id:
            return

        current_patient = chat_ctx.patient_contexts.get(chat_ctx.patient_id)
        if not current_patient:
            logger.warning(f"No patient context found for {chat_ctx.patient_id}")
            return

        # Simple registry entry
        registry_entry = {
            "patient_id": chat_ctx.patient_id,
            "facts": current_patient.facts,
            "conversation_id": chat_ctx.conversation_id
        }

        try:
            await self.registry_accessor.update_patient_registry(
                chat_ctx.conversation_id,
                chat_ctx.patient_id,
                registry_entry,
                chat_ctx.patient_id  # Set as active patient
            )
            logger.info(f"Updated registry storage for {chat_ctx.patient_id}")
        except Exception as e:
            logger.warning(f"Failed to update registry storage: {e}")

    def _remove_system_message(self, chat_ctx: ChatContext):
        """Remove patient context system messages."""
        if not chat_ctx.patient_id:
            return

        current_patient_id = chat_ctx.patient_id
        messages_to_keep = []
        removed_count = 0

        for m in chat_ctx.chat_history.messages:
            if (m.role == AuthorRole.SYSTEM and m.items and len(m.items) > 0):
                content_str = m.items[0].text if hasattr(m.items[0], 'text') else str(m.items[0])
                if content_str.startswith(PATIENT_CONTEXT_PREFIX):
                    try:
                        json_content = content_str[len(PATIENT_CONTEXT_PREFIX):].strip()
                        if json_content.startswith(":"):
                            json_content = json_content[1:].strip()
                        payload = json.loads(json_content)
                        if payload.get("patient_id") == current_patient_id:
                            removed_count += 1
                            continue  # Skip this message (remove it)
                    except Exception:
                        pass  # Keep malformed messages

            messages_to_keep.append(m)

        if removed_count > 0:
            logger.debug(f"Removed {removed_count} system messages for {current_patient_id}")

        chat_ctx.chat_history.messages = messages_to_keep

    async def _try_restore_specific_patient(self, patient_id: str, chat_ctx: ChatContext) -> bool:
        """Try to restore specific patient from storage."""
        # Try registry storage first
        if self.registry_accessor:
            try:
                patient_registry, _ = await self.registry_accessor.read_registry(chat_ctx.conversation_id)
                if patient_id in patient_registry:
                    registry_entry = patient_registry[patient_id]
                    chat_ctx.patient_contexts[patient_id] = PatientContext(
                        patient_id=patient_id,
                        facts=registry_entry.get("facts", {})
                    )
                    logger.info(f"Restored {patient_id} from registry storage")
                    return True
            except Exception as e:
                logger.warning(f"Failed to restore {patient_id} from registry: {e}")

        # Try patient-specific context file
        if self.context_accessor:
            try:
                stored_ctx = await self.context_accessor.read(chat_ctx.conversation_id, patient_id)
                if stored_ctx and patient_id in stored_ctx.patient_contexts:
                    stored_context = stored_ctx.patient_contexts[patient_id]
                    chat_ctx.patient_contexts[patient_id] = PatientContext(
                        patient_id=patient_id,
                        facts=getattr(stored_context, 'facts', {})
                    )
                    logger.info(f"Restored {patient_id} from patient-specific context")
                    return True
            except Exception as e:
                logger.warning(f"Failed to restore {patient_id} from context: {e}")

        return False

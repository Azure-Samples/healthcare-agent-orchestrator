import json
import logging
import re
import time
from datetime import datetime, timezone
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
    Registry-based patient context manager:
    1. Patient registry is the single source of truth for patient metadata
    2. Use analyzer to detect explicit patient IDs
    3. Fall back to storage if analyzer returns NONE
    4. Simple file-based patient isolation for chat history
    5. Kernel reset on patient switches
    """

    def __init__(self, analyzer: PatientContextAnalyzer, registry_accessor=None, context_accessor=None):
        self.analyzer = analyzer
        self.registry_accessor = registry_accessor
        self.context_accessor = context_accessor
        logger.info("PatientContextService initialized with storage fallback: %s", registry_accessor is not None)

    async def _ensure_patient_contexts_from_registry(self, chat_ctx: ChatContext):
        """Ensure patient_contexts is populated from registry (single source of truth)."""
        if not self.registry_accessor:
            return

        try:
            patient_registry, _ = await self.registry_accessor.read_registry(chat_ctx.conversation_id)
            if patient_registry:
                # Clear and rebuild from registry
                chat_ctx.patient_contexts.clear()
                for patient_id, registry_entry in patient_registry.items():
                    chat_ctx.patient_contexts[patient_id] = PatientContext(
                        patient_id=patient_id,
                        facts=registry_entry.get("facts", {})
                    )
                logger.debug("Loaded %d patients from registry", len(patient_registry))
        except Exception as e:
            logger.warning("Failed to load patient contexts from registry: %s", e)

    async def decide_and_apply(self, user_text: str, chat_ctx: ChatContext) -> tuple[Decision, TimingInfo]:
        service_start_time = time.time()

        # FIRST: Ensure we have latest patient contexts from registry
        await self._ensure_patient_contexts_from_registry(chat_ctx)

        # Skip analyzer for very short messages that are likely agent handoffs
        if user_text and len(user_text.strip()) <= 15 and not any(
            word in user_text.lower() for word in ["patient", "clear", "switch"]
        ):
            logger.info("Skipping analyzer for short handoff message: '%s'", user_text)

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

        logger.info("Patient context decision for '%s' | Current patient: %s", user_text, chat_ctx.patient_id)

        # STEP 1: Run the analyzer with structured output
        decision_model, analyzer_duration = await self.analyzer.analyze_with_timing(
            user_text=user_text,
            prior_patient_id=chat_ctx.patient_id,
            known_patient_ids=list(chat_ctx.patient_contexts.keys()),
        )

        action = decision_model.action
        pid = decision_model.patient_id

        logger.info(
            "Analyzer decision: %s | Patient ID: %s | Reasoning: %s",
            action, pid, decision_model.reasoning
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
                logger.warning("Invalid patient ID from analyzer: %s", pid)
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
        # Ensure we have latest patient contexts from registry
        await self._ensure_patient_contexts_from_registry(chat_ctx)

        if not patient_id or not PATIENT_ID_PATTERN.match(patient_id):
            logger.warning("Invalid patient ID format: %s", patient_id)
            return False

        if chat_ctx.patient_id and patient_id != chat_ctx.patient_id:
            logger.info("Resetting kernel for explicit patient switch: %s -> %s", chat_ctx.patient_id, patient_id)
            self.analyzer.reset_kernel()

        restored = await self._try_restore_specific_patient(patient_id, chat_ctx)
        if not restored:
            chat_ctx.patient_contexts[patient_id] = PatientContext(patient_id=patient_id)
            logger.info("Created new patient context: %s", patient_id)

        chat_ctx.patient_id = patient_id
        timing = TimingInfo(analyzer=0.0, storage_fallback=0.0, service=0.0)
        await self._ensure_system_message(chat_ctx, timing)

        if self.registry_accessor:
            try:
                await self._update_registry_storage(chat_ctx)
            except Exception as e:
                logger.warning("Failed to update registry storage: %s", e)

        return True

    async def _ensure_system_message(self, chat_ctx: ChatContext, timing: TimingInfo):
        """Ensure system message with patient context data using structured model."""
        self._remove_system_message(chat_ctx)

        if not chat_ctx.patient_id:
            return

        # Get all session patients from registry (single source of truth)
        all_patient_ids = []
        if self.registry_accessor:
            try:
                patient_registry, _ = await self.registry_accessor.read_registry(chat_ctx.conversation_id)
                if patient_registry:
                    all_patient_ids = list(patient_registry.keys())
                    logger.debug("Using patient registry for system message: %s", all_patient_ids)
            except Exception as e:
                logger.warning("Failed to read patient registry for system message: %s", e)
                # Fallback to in-memory contexts
                all_patient_ids = list(chat_ctx.patient_contexts.keys())
        else:
            # Fallback to in-memory contexts
            all_patient_ids = list(chat_ctx.patient_contexts.keys())

        # Use structured model for system message
        payload = PatientContextSystemMessage(
            conversation_id=chat_ctx.conversation_id,
            patient_id=chat_ctx.patient_id,
            all_patient_ids=all_patient_ids,
            timing_sec=timing,
        )

        line = "%s: %s" % (PATIENT_CONTEXT_PREFIX, payload.model_dump_json())
        system_message = ChatMessageContent(
            role=AuthorRole.SYSTEM,
            items=[TextContent(text=line)]
        )
        chat_ctx.chat_history.messages.insert(0, system_message)
        logger.debug(
            "Added structured patient context system message for %s with %d session patients",
            chat_ctx.patient_id, len(all_patient_ids)
        )

    async def _try_restore_from_storage(self, chat_ctx: ChatContext) -> bool:
        """Try to restore patient context from storage files."""
        logger.info("Attempting storage fallback for conversation: %s", chat_ctx.conversation_id)

        # Load latest patient contexts from registry
        await self._ensure_patient_contexts_from_registry(chat_ctx)

        # Priority 1: Check patient registry file (session registry)
        if self.registry_accessor:
            try:
                patient_registry, active_patient_id = await self.registry_accessor.read_registry(chat_ctx.conversation_id)

                if patient_registry and active_patient_id:
                    logger.info("Found %d patients. Active: %s", len(patient_registry), active_patient_id)

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
                                    logger.info("Loaded isolated chat history for: %s", active_patient_id)
                            except Exception as e:
                                logger.warning("Failed to load patient-specific chat history: %s", e)

                        logger.info("Restored active patient: %s", active_patient_id)
                        return True
            except Exception as e:
                logger.warning("Failed to read patient registry: %s", e)

        # Priority 2: Check session context (legacy fallback)
        if self.context_accessor:
            try:
                restored_ctx = await self.context_accessor.read(chat_ctx.conversation_id)
                if restored_ctx and restored_ctx.patient_id:
                    chat_ctx.patient_id = restored_ctx.patient_id
                    # Note: Don't restore patient_contexts from file - use registry only
                    chat_ctx.chat_history = restored_ctx.chat_history or chat_ctx.chat_history
                    logger.info("Restored session context: %s", restored_ctx.patient_id)
                    return True
            except Exception as e:
                logger.warning("Failed to read session context: %s", e)

        logger.info("No patient context found in storage")
        return False

    async def _archive_all_and_recreate(self, chat_ctx: ChatContext) -> None:
        """Archive all files to blob storage and recreate fresh files."""
        logger.info("Archiving all contexts to blob storage for conversation: %s", chat_ctx.conversation_id)

        # Kernel reset for complete context clear
        if chat_ctx.patient_id:
            logger.info("Resetting kernel for complete context clear")
            self.analyzer.reset_kernel()

        archive_failures = []

        # Get ALL patients from registry (single source of truth)
        all_patient_ids = []
        if self.registry_accessor:
            try:
                patient_registry, _ = await self.registry_accessor.read_registry(chat_ctx.conversation_id)
                if patient_registry:
                    all_patient_ids = list(patient_registry.keys())
                    logger.info("Found %d patients in registry to archive: %s", len(all_patient_ids), all_patient_ids)
                else:
                    logger.warning("No patient registry found for archival")
            except Exception as e:
                logger.warning("Failed to read patient registry for archival: %s", e)
                # Fallback to in-memory contexts
                all_patient_ids = list(chat_ctx.patient_contexts.keys())

        # Create timestamped archive folder
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
        archive_folder = "archive/%s" % timestamp

        try:
            logger.info("Starting archive to folder: %s", archive_folder)

            # Archive session context (main conversation)
            if self.context_accessor:
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
            logger.info("Resetting kernel for patient switch: %s -> %s", chat_ctx.patient_id, patient_id)
            self.analyzer.reset_kernel()

        # Ensure we have latest registry data
        await self._ensure_patient_contexts_from_registry(chat_ctx)

        # Check if we have registry data for this patient
        if self.registry_accessor:
            try:
                patient_registry, _ = await self.registry_accessor.read_registry(chat_ctx.conversation_id)
                if patient_id in patient_registry:
                    # Patient exists in registry
                    chat_ctx.patient_id = patient_id

                    # Load isolated chat history for this patient
                    if self.context_accessor:
                        try:
                            restored_chat_ctx = await self.context_accessor.read(chat_ctx.conversation_id, patient_id)
                            if restored_chat_ctx and hasattr(restored_chat_ctx, 'chat_history'):
                                # Clear current history and load patient-specific history
                                chat_ctx.chat_history.messages.clear()
                                chat_ctx.chat_history.messages.extend(restored_chat_ctx.chat_history.messages)
                                logger.info("Loaded isolated chat history for: %s", patient_id)
                        except Exception as e:
                            logger.warning("Failed to load patient-specific chat history: %s", e)

                    logger.info("Switched to existing patient from registry: %s", patient_id)
                    # CRITICAL: Update registry to mark this patient as currently active
                    await self._update_registry_storage(chat_ctx)

                    return "SWITCH_EXISTING"
            except Exception as e:
                logger.warning("Failed to check registry for %s: %s", patient_id, e)

        # Switch to existing in memory - PRESERVE CHAT HISTORY
        if patient_id in chat_ctx.patient_contexts:
            chat_ctx.patient_id = patient_id
            logger.info("Switched to existing patient (preserving chat history): %s", patient_id)
            # Update registry when switching to existing patient
            await self._update_registry_storage(chat_ctx)
            return "SWITCH_EXISTING"

        # New blank patient context - PRESERVE CHAT HISTORY
        chat_ctx.patient_contexts[patient_id] = PatientContext(patient_id=patient_id)
        chat_ctx.patient_id = patient_id
        logger.info("Created new patient context (preserving chat history): %s", patient_id)

        # CRITICAL: Update registry storage for new patient
        await self._update_registry_storage(chat_ctx)

        return "NEW_BLANK"

    async def _update_registry_storage(self, chat_ctx: ChatContext):
        """Update registry storage for current patient."""
        if not self.registry_accessor or not chat_ctx.patient_id:
            return

        current_patient = chat_ctx.patient_contexts.get(chat_ctx.patient_id)
        if not current_patient:
            logger.warning("No patient context found for %s", chat_ctx.patient_id)
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
            logger.info("Updated registry storage for %s", chat_ctx.patient_id)
        except Exception as e:
            logger.warning("Failed to update registry storage: %s", e)

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
            logger.debug("Removed %d system messages for %s", removed_count, current_patient_id)

        chat_ctx.chat_history.messages = messages_to_keep

    async def _try_restore_specific_patient(self, patient_id: str, chat_ctx: ChatContext) -> bool:
        """Try to restore specific patient from storage."""
        # Try registry storage first (single source of truth)
        if self.registry_accessor:
            try:
                patient_registry, _ = await self.registry_accessor.read_registry(chat_ctx.conversation_id)
                if patient_id in patient_registry:
                    registry_entry = patient_registry[patient_id]
                    chat_ctx.patient_contexts[patient_id] = PatientContext(
                        patient_id=patient_id,
                        facts=registry_entry.get("facts", {})
                    )
                    logger.info("Restored %s from registry storage", patient_id)
                    return True
            except Exception as e:
                logger.warning("Failed to restore %s from registry: %s", patient_id, e)

        # Legacy fallback: Try patient-specific context file (deprecated)
        if self.context_accessor:
            try:
                stored_ctx = await self.context_accessor.read(chat_ctx.conversation_id, patient_id)
                if stored_ctx and hasattr(stored_ctx, 'patient_contexts') and patient_id in stored_ctx.patient_contexts:
                    stored_context = stored_ctx.patient_contexts[patient_id]
                    chat_ctx.patient_contexts[patient_id] = PatientContext(
                        patient_id=patient_id,
                        facts=getattr(stored_context, 'facts', {})
                    )
                    logger.info("Restored %s from patient-specific context (legacy)", patient_id)
                    return True
            except Exception as e:
                logger.warning("Failed to restore %s from context: %s", patient_id, e)

        return False

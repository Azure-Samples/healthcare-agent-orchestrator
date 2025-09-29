# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging
import re
import time
from datetime import datetime, timezone
from typing import Literal

from data_models.chat_context import ChatContext, PatientContext
from data_models.patient_context_models import TimingInfo
from services.patient_context_analyzer import PatientContextAnalyzer

logger = logging.getLogger(__name__)

# Keep the constant so other modules (routes, bots) can import it
PATIENT_CONTEXT_PREFIX = "PATIENT_CONTEXT_JSON"
PATIENT_ID_PATTERN = re.compile(r"^patient_[0-9]+$")
Decision = Literal["NONE", "UNCHANGED", "NEW_BLANK", "SWITCH_EXISTING",
                   "CLEAR", "RESTORED_FROM_STORAGE", "NEEDS_PATIENT_ID"]


class PatientContextService:
    """
    Registry-based patient context manager (clean version):
    - Registry is authoritative for patient roster.
    - Analyzer decides patient activation/switch/clear.
    - No system message persistence (ephemeral injection happens outside this service).
    - Per-patient chat history isolation performed by caller (route/bot) AFTER decision.
    """

    def __init__(self, analyzer: PatientContextAnalyzer, registry_accessor=None, context_accessor=None):
        self.analyzer = analyzer
        self.registry_accessor = registry_accessor
        self.context_accessor = context_accessor
        logger.info("PatientContextService initialized (registry enabled: %s)", registry_accessor is not None)

    async def _ensure_patient_contexts_from_registry(self, chat_ctx: ChatContext):
        """Rebuild in-memory patient_contexts from registry snapshot each turn."""
        if not self.registry_accessor:
            return
        try:
            patient_registry, _ = await self.registry_accessor.read_registry(chat_ctx.conversation_id)
            chat_ctx.patient_contexts.clear()
            if patient_registry:
                for pid, entry in patient_registry.items():
                    chat_ctx.patient_contexts[pid] = PatientContext(
                        patient_id=pid,
                        facts=entry.get("facts", {})
                    )
        except Exception as e:
            logger.warning("Failed to load patient contexts from registry: %s", e)

    async def decide_and_apply(self, user_text: str, chat_ctx: ChatContext) -> tuple[Decision, TimingInfo]:
        service_start = time.time()

        # Always refresh from registry first
        await self._ensure_patient_contexts_from_registry(chat_ctx)

        # Short heuristic skip
        if user_text and len(user_text.strip()) <= 15 and not any(
            k in user_text.lower() for k in ["patient", "clear", "switch"]
        ):
            if not chat_ctx.patient_id:
                fb_start = time.time()
                restored = await self._try_restore_from_storage(chat_ctx)
                fb_dur = time.time() - fb_start
                timing = TimingInfo(analyzer=0.0, storage_fallback=fb_dur, service=time.time() - service_start)
                return ("RESTORED_FROM_STORAGE" if restored else "NONE", timing)
            timing = TimingInfo(analyzer=0.0, storage_fallback=0.0, service=time.time() - service_start)
            return "UNCHANGED", timing

        decision_model, analyzer_dur = await self.analyzer.analyze_with_timing(
            user_text=user_text,
            prior_patient_id=chat_ctx.patient_id,
            known_patient_ids=list(chat_ctx.patient_contexts.keys()),
        )

        action = decision_model.action
        pid = decision_model.patient_id
        fallback_dur = 0.0

        if action == "CLEAR":
            await self._archive_all_and_recreate(chat_ctx)
            timing = TimingInfo(analyzer=analyzer_dur, storage_fallback=0.0, service=time.time() - service_start)
            return "CLEAR", timing

        if action in ("ACTIVATE_NEW", "SWITCH_EXISTING"):
            if not pid or not PATIENT_ID_PATTERN.match(pid):
                decision = "NEEDS_PATIENT_ID"
            else:
                decision = await self._activate_patient_with_registry(pid, chat_ctx)
        elif action == "NONE":
            if not chat_ctx.patient_id:
                fb_start = time.time()
                restored = await self._try_restore_from_storage(chat_ctx)
                fallback_dur = time.time() - fb_start
                decision = "RESTORED_FROM_STORAGE" if restored else "NONE"
            else:
                decision = "UNCHANGED"
        elif action == "UNCHANGED":
            decision = "UNCHANGED"
        else:
            decision = "NONE"

        timing = TimingInfo(
            analyzer=analyzer_dur,
            storage_fallback=fallback_dur,
            service=time.time() - service_start
        )
        # NOTE: No system message injection here (handled by caller).
        return decision, timing

    async def set_explicit_patient_context(self, patient_id: str, chat_ctx: ChatContext) -> bool:
        if not patient_id or not PATIENT_ID_PATTERN.match(patient_id):
            return False

        if chat_ctx.patient_id and patient_id != chat_ctx.patient_id:
            self.analyzer.reset_kernel()

        await self._ensure_patient_contexts_from_registry(chat_ctx)

        if patient_id not in chat_ctx.patient_contexts:
            chat_ctx.patient_contexts[patient_id] = PatientContext(patient_id=patient_id)

        chat_ctx.patient_id = patient_id

        if self.registry_accessor:
            await self._update_registry_storage(chat_ctx)
        return True

    async def _archive_all_and_recreate(self, chat_ctx: ChatContext) -> None:
        """Archive all session + patient files + registry then clear memory."""
        if chat_ctx.patient_id:
            self.analyzer.reset_kernel()

        all_patient_ids = []
        if self.registry_accessor:
            try:
                patient_registry, _ = await self.registry_accessor.read_registry(chat_ctx.conversation_id)
                all_patient_ids = list(patient_registry.keys()) if patient_registry else []
            except Exception:
                all_patient_ids = list(chat_ctx.patient_contexts.keys())

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
        folder = f"archive/{timestamp}"

        if self.context_accessor:
            try:
                await self.context_accessor.archive_to_folder(chat_ctx.conversation_id, None, folder)
            except Exception as e:
                logger.warning("Archive session failed: %s", e)
            for pid in all_patient_ids:
                try:
                    await self.context_accessor.archive_to_folder(chat_ctx.conversation_id, pid, folder)
                except Exception as e:
                    logger.warning("Archive patient %s failed: %s", pid, e)

        if self.registry_accessor:
            try:
                await self.registry_accessor.archive_registry(chat_ctx.conversation_id)
            except Exception as e:
                logger.warning("Archive registry failed: %s", e)

        chat_ctx.patient_id = None
        chat_ctx.patient_contexts.clear()
        chat_ctx.chat_history.messages.clear()

    async def _update_registry_storage(self, chat_ctx: ChatContext):
        if not (self.registry_accessor and chat_ctx.patient_id):
            return
        current = chat_ctx.patient_contexts.get(chat_ctx.patient_id)
        if not current:
            return
        entry = {
            "patient_id": chat_ctx.patient_id,
            "facts": current.facts,
            "conversation_id": chat_ctx.conversation_id
        }
        try:
            await self.registry_accessor.update_patient_registry(
                chat_ctx.conversation_id,
                chat_ctx.patient_id,
                entry,
                chat_ctx.patient_id
            )
        except Exception as e:
            logger.warning("Failed registry update: %s", e)

    async def _activate_patient_with_registry(self, patient_id: str, chat_ctx: ChatContext) -> Decision:
        if chat_ctx.patient_id == patient_id:
            return "UNCHANGED"
        if chat_ctx.patient_id and patient_id != chat_ctx.patient_id:
            self.analyzer.reset_kernel()

        await self._ensure_patient_contexts_from_registry(chat_ctx)

        if patient_id in chat_ctx.patient_contexts:
            chat_ctx.patient_id = patient_id
            await self._update_registry_storage(chat_ctx)
            return "SWITCH_EXISTING"

        chat_ctx.patient_contexts[patient_id] = PatientContext(patient_id=patient_id)
        chat_ctx.patient_id = patient_id
        await self._update_registry_storage(chat_ctx)
        return "NEW_BLANK"

    async def _try_restore_from_storage(self, chat_ctx: ChatContext) -> bool:
        """Restore active patient from registry (no legacy file scanning)."""
        if not self.registry_accessor:
            return False
        try:
            patient_registry, active = await self.registry_accessor.read_registry(chat_ctx.conversation_id)
            if patient_registry and active and active in patient_registry:
                await self._ensure_patient_contexts_from_registry(chat_ctx)
                chat_ctx.patient_id = active
                return True
        except Exception as e:
            logger.warning("Restore from registry failed: %s", e)
        return False

# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging
import re
import time
from datetime import datetime, timezone
from typing import Literal
import os

from data_models.chat_context import ChatContext, PatientContext
from data_models.patient_context_models import TimingInfo
from services.patient_context_analyzer import PatientContextAnalyzer

logger = logging.getLogger(__name__)

# Exported constants / types
PATIENT_CONTEXT_PREFIX = "PATIENT_CONTEXT_JSON"
PATIENT_ID_PATTERN = re.compile(os.getenv("PATIENT_ID_PATTERN", r"^patient_[0-9]+$"))
Decision = Literal[
    "NONE",
    "UNCHANGED",
    "NEW_BLANK",
    "SWITCH_EXISTING",
    "CLEAR",
    "RESTORED_FROM_STORAGE",
    "NEEDS_PATIENT_ID",
]


class PatientContextService:
    """
    Registry-based patient context manager:
    - Registry is authoritative patient roster + active pointer.
    - Analyzer determines activation/switch/clear intent.
    - Ephemeral system snapshot injection is performed by caller (routes/bots).
    - Per‑patient isolation for chat history handled by caller after decision.
    """

    def __init__(self, analyzer: PatientContextAnalyzer, registry_accessor=None, context_accessor=None):
        self.analyzer = analyzer
        self.registry_accessor = registry_accessor
        self.context_accessor = context_accessor
        logger.info(
            "PatientContextService initialized (registry enabled: %s)",
            registry_accessor is not None,
        )

    async def _ensure_patient_contexts_from_registry(self, chat_ctx: ChatContext):
        """
        Rebuild in-memory patient_contexts from the authoritative registry each turn.
        Safe to call every turn (clears and repopulates).
        """
        if not self.registry_accessor:
            return
        try:
            patient_registry, _ = await self.registry_accessor.read_registry(chat_ctx.conversation_id)
            chat_ctx.patient_contexts.clear()
            if patient_registry:
                for pid, entry in patient_registry.items():
                    chat_ctx.patient_contexts[pid] = PatientContext(
                        patient_id=pid,
                        facts=entry.get("facts", {}),
                    )
        except Exception as e:
            logger.warning("Failed to load patient contexts from registry: %s", e)

    async def decide_and_apply(self, user_text: str, chat_ctx: ChatContext) -> tuple[Decision, TimingInfo]:
        """
        Analyze user input, decide patient context transition, and apply.
        Flow:
          1. Hydrate registry → in-memory contexts.
          2. If no active patient, attempt silent restore (record timing if used).
          3. Always run analyzer (enables first-turn activation).
          4. Interpret analyzer action into service Decision.
          5. Perform activation / switch / clear side-effects.
          6. Return (Decision, TimingInfo).
        """
        service_start = time.time()
        await self._ensure_patient_contexts_from_registry(chat_ctx)

        restored = False
        fallback_dur = 0.0
        if not chat_ctx.patient_id:
            fb_start = time.time()
            if await self._try_restore_from_storage(chat_ctx):
                restored = True
                fallback_dur = time.time() - fb_start

        decision_model, analyzer_dur = await self.analyzer.analyze_with_timing(
            user_text=user_text,
            prior_patient_id=chat_ctx.patient_id,
            known_patient_ids=list(chat_ctx.patient_contexts.keys()),
        )
        action = decision_model.action
        pid = decision_model.patient_id

        if action == "CLEAR":
            await self._archive_all_and_recreate(chat_ctx)
            timing = TimingInfo(
                analyzer=analyzer_dur,
                storage_fallback=fallback_dur,
                service=time.time() - service_start,
            )
            return "CLEAR", timing

        if action in ("ACTIVATE_NEW", "SWITCH_EXISTING"):
            if not pid or not PATIENT_ID_PATTERN.match(pid):
                decision: Decision = "NEEDS_PATIENT_ID"
            else:
                decision = await self._activate_patient_with_registry(pid, chat_ctx)
        elif action == "UNCHANGED":
            decision = "UNCHANGED"
        elif action == "NONE":
            decision = "RESTORED_FROM_STORAGE" if restored and chat_ctx.patient_id else "NONE"
        else:
            decision = "NONE"

        timing = TimingInfo(
            analyzer=analyzer_dur,
            storage_fallback=fallback_dur,
            service=time.time() - service_start,
        )
        return decision, timing

    async def set_explicit_patient_context(self, patient_id: str, chat_ctx: ChatContext) -> bool:
        """
        Explicitly set active patient (external caller / override path).
        Returns True if set; False if invalid patient_id.
        """
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
        """
        Archive session + all patient histories + registry, then clear in-memory state.
        """
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
            # Session
            try:
                await self.context_accessor.archive_to_folder(chat_ctx.conversation_id, None, folder)
            except Exception as e:
                logger.warning("Archive session failed: %s", e)
            # Each patient
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

    async def _update_registry_storage(self, chat_ctx: ChatContext):
        """
        Write/merge current active patient entry into registry (active pointer updated).
        """
        if not (self.registry_accessor and chat_ctx.patient_id):
            return
        current = chat_ctx.patient_contexts.get(chat_ctx.patient_id)
        if not current:
            return
        entry = {
            "patient_id": chat_ctx.patient_id,
            "facts": current.facts,
            "conversation_id": chat_ctx.conversation_id,
        }
        try:
            await self.registry_accessor.update_patient_registry(
                chat_ctx.conversation_id,
                chat_ctx.patient_id,
                entry,
                chat_ctx.patient_id,  # update active pointer
            )
        except Exception as e:
            logger.warning("Failed registry update: %s", e)

    async def _activate_patient_with_registry(self, patient_id: str, chat_ctx: ChatContext) -> Decision:
        """
        Activate or switch patient. Returns:
          - UNCHANGED if already active
          - SWITCH_EXISTING if switching to existing
          - NEW_BLANK if creating a new patient context
        """
        if chat_ctx.patient_id == patient_id:
            return "UNCHANGED"
        if chat_ctx.patient_id and patient_id != chat_ctx.patient_id:
            self.analyzer.reset_kernel()

        await self._ensure_patient_contexts_from_registry(chat_ctx)

        if patient_id in chat_ctx.patient_contexts:
            chat_ctx.patient_id = patient_id
            await self._update_registry_storage(chat_ctx)
            return "SWITCH_EXISTING"

        # New patient
        chat_ctx.patient_contexts[patient_id] = PatientContext(patient_id=patient_id)
        chat_ctx.patient_id = patient_id
        await self._update_registry_storage(chat_ctx)
        return "NEW_BLANK"

    async def _try_restore_from_storage(self, chat_ctx: ChatContext) -> bool:
        """
        If there is no active patient in-memory, attempt to restore last active from registry.
        Returns True if restored.
        """
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

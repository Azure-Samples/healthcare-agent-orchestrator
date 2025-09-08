# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
from dataclasses import dataclass, field
from typing import Dict, Any

from semantic_kernel.contents.chat_history import ChatHistory


@dataclass
class PatientContext:
    """
    Minimal per-patient context (future expansion point: facts, summary, provenance).
    """
    patient_id: str
    facts: Dict[str, Any] = field(default_factory=dict)  # placeholder for future enrichment


class ChatContext:
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.chat_history = ChatHistory()

        # Active patient (single pointer)
        self.patient_id = None

        # All encountered patient contexts (allows switching back without re-extraction)
        self.patient_contexts: Dict[str, PatientContext] = {}

        # Existing fields
        self.patient_data = []
        self.display_blob_urls = []
        self.display_image_urls = []
        self.display_clinical_trials = []
        self.output_data = []
        self.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.healthcare_agents = {}
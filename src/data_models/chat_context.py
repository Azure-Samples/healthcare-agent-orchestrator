# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
from dataclasses import dataclass, field
from typing import Dict, Any

from semantic_kernel.contents.chat_history import ChatHistory


@dataclass
class PatientContext:
    """
    Minimal per-patient context for patient isolation.
    """
    patient_id: str
    facts: Dict[str, Any] = field(default_factory=dict)


class ChatContext:
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.chat_history = ChatHistory()

        # Patient context fields
        self.patient_id = None
        self.patient_contexts: Dict[str, PatientContext] = {}

        # Legacy / display fields (still in use by various UI & agents)
        self.patient_data = []
        self.display_blob_urls = []
        self.display_image_urls = []
        self.display_clinical_trials = []
        self.output_data = []
        self.healthcare_agents = {}
        self.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

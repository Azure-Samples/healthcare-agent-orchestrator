from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Literal
from pydantic import BaseModel

# Canonical analyzer action literal (shared across analyzer + service typing)
AnalyzerAction = Literal[
    "NONE",
    "CLEAR",
    "ACTIVATE_NEW",
    "SWITCH_EXISTING",
    "UNCHANGED",
]


class PatientContextDecision(BaseModel):
    """
    Structured output returned by the patient context analyzer.
    - action: one of AnalyzerAction
    - patient_id: only populated when action implies activation/switch; otherwise None
    - reasoning: brief natural language explanation (kept short by prompt)
    """
    action: AnalyzerAction
    patient_id: Optional[str]
    reasoning: str


@dataclass
class TimingInfo:
    """
    Timing breakdown for a single patient context decision cycle.
    All values are seconds (float) measured with time.time() deltas.
    - analyzer: model inference / structured output duration
    - storage_fallback: time spent attempting restore-from-storage fallback (if any)
    - service: total wall-clock for decide_and_apply orchestration
    """
    analyzer: float
    storage_fallback: float
    service: float

# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional, List, Literal
from semantic_kernel.kernel_pydantic import KernelBaseModel
from pydantic import BaseModel, Field

# Update this to match your current analyzer actions
AnalyzerAction = Literal["NONE", "CLEAR", "ACTIVATE_NEW", "SWITCH_EXISTING", "UNCHANGED"]


class TimingInfo(BaseModel):
    """Timing information for patient context operations."""
    analyzer: float = Field(0.0, description="Time spent in analyzer (seconds)")
    storage_fallback: float = Field(0.0, description="Time spent in storage fallback (seconds)")
    service: float = Field(0.0, description="Total service processing time (seconds)")


class PatientContextDecision(KernelBaseModel):
    """
    Structured output for patient context analysis decisions.
    Uses KernelBaseModel for proper JSON schema generation with Semantic Kernel.
    """
    action: AnalyzerAction = Field(
        ...,
        description="The action to take: NONE, CLEAR, ACTIVATE_NEW, SWITCH_EXISTING, or UNCHANGED"
    )
    patient_id: Optional[str] = Field(
        None,
        description="The patient ID if the action involves a specific patient (format: patient_X)"
    )
    reasoning: str = Field(
        ...,
        description="Brief explanation of why this decision was made (max 50 words)"
    )


class WorkflowStep(BaseModel):
    """A single step in the workflow plan."""
    agent: str = Field(..., description="Name of the agent responsible for this step")
    task: str = Field(..., description="Description of the task to be performed")
    status: str = Field("pending", description="Status: pending, in_progress, completed")


class WorkflowSummary(KernelBaseModel):
    """
    Structured workflow summary for tracking conversation progress.
    Uses KernelBaseModel for proper JSON schema generation with Semantic Kernel.
    """
    patient_id: Optional[str] = Field(None, description="The patient ID this workflow relates to (if applicable)")
    objective: str = Field(..., description="The main objective of this workflow")
    steps: List[WorkflowStep] = Field(..., description="List of workflow steps")
    current_step: int = Field(0, description="Index of the current step being executed")
    reasoning: str = Field(..., description="Summary of the workflow reasoning")


class PatientContextSystemMessage(KernelBaseModel):
    """System message payload for patient context."""
    conversation_id: str = Field(..., description="Conversation identifier")
    patient_id: str = Field(..., description="Active patient identifier")
    all_patient_ids: List[str] = Field(..., description="All known patient IDs in this session")
    timing_sec: TimingInfo = Field(..., description="Timing information for this operation")


class PatientRegistryEntry(BaseModel):
    """Registry entry for patient tracking."""
    patient_id: str = Field(..., description="Patient identifier")
    created_at: str = Field(..., description="ISO timestamp when patient was created")
    last_accessed: str = Field(..., description="ISO timestamp when patient was last accessed")
    message_count: int = Field(0, description="Number of messages for this patient")
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


# Update this to match your current analyzer actions
AnalyzerAction = Literal["NONE", "CLEAR", "ACTIVATE_NEW", "SWITCH_EXISTING", "UNCHANGED"]


class TimingInfo(BaseModel):
    """Timing information for patient context operations."""
    analyzer: float = Field(0.0, description="Time spent in analyzer (seconds)")
    storage_fallback: float = Field(0.0, description="Time spent in storage fallback (seconds)")
    service: float = Field(0.0, description="Total service processing time (seconds)")


class PatientContextDecision(KernelBaseModel):
    """
    Structured output for patient context analysis decisions.
    Uses KernelBaseModel for proper JSON schema generation with Semantic Kernel.
    """
    action: AnalyzerAction = Field(
        ...,
        description="The action to take: NONE, CLEAR, ACTIVATE_NEW, SWITCH_EXISTING, or UNCHANGED"
    )
    patient_id: Optional[str] = Field(
        None,
        description="The patient ID if the action involves a specific patient (format: patient_X)"
    )
    reasoning: str = Field(
        ...,
        description="Brief explanation of why this decision was made (max 50 words)"
    )


class WorkflowStep(BaseModel):
    """A single step in the workflow plan."""
    agent: str = Field(..., description="Name of the agent responsible for this step")
    task: str = Field(..., description="Description of the task to be performed")
    status: str = Field("pending", description="Status: pending, in_progress, completed")


class WorkflowSummary(KernelBaseModel):
    """
    Structured workflow summary for tracking conversation progress.
    Uses KernelBaseModel for proper JSON schema generation with Semantic Kernel.
    """
    patient_id: Optional[str] = Field(None, description="The patient ID this workflow relates to (if applicable)")
    objective: str = Field(..., description="The main objective of this workflow")
    steps: List[WorkflowStep] = Field(..., description="List of workflow steps")
    current_step: int = Field(0, description="Index of the current step being executed")
    reasoning: str = Field(..., description="Summary of the workflow reasoning")


class PatientContextSystemMessage(KernelBaseModel):
    """System message payload for patient context."""
    conversation_id: str = Field(..., description="Conversation identifier")
    patient_id: str = Field(..., description="Active patient identifier")
    all_patient_ids: List[str] = Field(..., description="All known patient IDs in this session")
    timing_sec: TimingInfo = Field(..., description="Timing information for this operation")


class PatientRegistryEntry(BaseModel):
    """Registry entry for patient tracking."""
    patient_id: str = Field(..., description="Patient identifier")
    created_at: str = Field(..., description="ISO timestamp when patient was created")
    last_accessed: str = Field(..., description="ISO timestamp when patient was last accessed")
    message_count: int = Field(0, description="Number of messages for this patient")

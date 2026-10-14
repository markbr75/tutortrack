"""Workflows defined by this app (autodiscovered by the worker)."""

from .check_processes import BackgroundCheckWorkflow
from .processes import (
    ComplianceRecordWorkflow,
    ReferenceRequestWorkflow,
    TutorApplicationWorkflow,
    TutorOnboardingWorkflow,
)

__all__ = [
    "BackgroundCheckWorkflow",
    "ComplianceRecordWorkflow",
    "ReferenceRequestWorkflow",
    "TutorApplicationWorkflow",
    "TutorOnboardingWorkflow",
]

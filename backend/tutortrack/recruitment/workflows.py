"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import (
    ComplianceRecordWorkflow,
    ReferenceRequestWorkflow,
    TutorApplicationWorkflow,
    TutorOnboardingWorkflow,
)

__all__ = [
    "ComplianceRecordWorkflow",
    "ReferenceRequestWorkflow",
    "TutorApplicationWorkflow",
    "TutorOnboardingWorkflow",
]

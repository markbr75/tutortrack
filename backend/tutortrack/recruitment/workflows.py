"""Workflows defined by this app (autodiscovered by the worker)."""

from .check_processes import BackgroundCheckWorkflow
from .processes import (
    ComplianceRecordWorkflow,
    ReferenceRequestWorkflow,
    TutorApplicationWorkflow,
    TutorOnboardingWorkflow,
)
from .review_processes import InterviewWorkflow, ProbationReviewWorkflow

__all__ = [
    "BackgroundCheckWorkflow",
    "ComplianceRecordWorkflow",
    "InterviewWorkflow",
    "ProbationReviewWorkflow",
    "ReferenceRequestWorkflow",
    "TutorApplicationWorkflow",
    "TutorOnboardingWorkflow",
]

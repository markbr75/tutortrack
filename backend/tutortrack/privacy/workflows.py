"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import (
    DataSubjectRequestWorkflow,
    ErasureWorkflow,
    LoneWorkingWorkflow,
    RetentionPurgeWorkflow,
)

__all__ = [
    "DataSubjectRequestWorkflow",
    "ErasureWorkflow",
    "LoneWorkingWorkflow",
    "RetentionPurgeWorkflow",
]

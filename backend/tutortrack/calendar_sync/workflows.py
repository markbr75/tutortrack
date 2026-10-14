"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import CalendarConnectionWorkflow, OnlineMeetingProvisioningWorkflow
from .video_processes import RecordingFetchWorkflow

__all__ = [
    "CalendarConnectionWorkflow",
    "OnlineMeetingProvisioningWorkflow",
    "RecordingFetchWorkflow",
]

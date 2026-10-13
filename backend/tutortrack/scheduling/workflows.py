"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import BookingHoldWorkflow, RescheduleRequestWorkflow, TimeOffApprovalWorkflow

__all__ = ["BookingHoldWorkflow", "RescheduleRequestWorkflow", "TimeOffApprovalWorkflow"]

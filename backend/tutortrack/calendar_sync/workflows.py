"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import CalendarConnectionWorkflow, OnlineMeetingProvisioningWorkflow

__all__ = ["CalendarConnectionWorkflow", "OnlineMeetingProvisioningWorkflow"]

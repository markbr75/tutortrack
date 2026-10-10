"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import AutomationRunWorkflow, AutomationScheduleWorkflow

__all__ = ["AutomationRunWorkflow", "AutomationScheduleWorkflow"]

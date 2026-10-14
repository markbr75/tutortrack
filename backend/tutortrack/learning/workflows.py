"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import HomeworkReminderWorkflow, LoanReminderWorkflow

__all__ = ["HomeworkReminderWorkflow", "LoanReminderWorkflow"]

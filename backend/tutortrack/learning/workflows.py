"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import HomeworkReminderWorkflow, LoanReminderWorkflow, ProgressReportRunWorkflow

__all__ = ["HomeworkReminderWorkflow", "LoanReminderWorkflow", "ProgressReportRunWorkflow"]

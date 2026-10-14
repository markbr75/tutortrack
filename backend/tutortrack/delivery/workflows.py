"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import LessonFeedbackWorkflow, LessonReportSlaWorkflow, UnconfirmedLessonWorkflow

__all__ = ["LessonFeedbackWorkflow", "LessonReportSlaWorkflow", "UnconfirmedLessonWorkflow"]

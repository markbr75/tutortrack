"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import LessonReportSlaWorkflow, UnconfirmedLessonWorkflow

__all__ = ["LessonReportSlaWorkflow", "UnconfirmedLessonWorkflow"]

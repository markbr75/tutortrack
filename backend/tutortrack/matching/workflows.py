"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import CoverRequestWorkflow, JobOfferCascadeWorkflow

__all__ = ["CoverRequestWorkflow", "JobOfferCascadeWorkflow"]

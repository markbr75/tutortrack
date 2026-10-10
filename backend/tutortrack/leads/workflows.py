"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import EnquiryFollowUpWorkflow, WaitlistOfferWorkflow

__all__ = ["EnquiryFollowUpWorkflow", "WaitlistOfferWorkflow"]

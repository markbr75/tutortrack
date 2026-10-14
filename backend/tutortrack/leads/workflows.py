"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import EnquiryFollowUpWorkflow, ProposalWorkflow, WaitlistOfferWorkflow

__all__ = ["EnquiryFollowUpWorkflow", "ProposalWorkflow", "WaitlistOfferWorkflow"]

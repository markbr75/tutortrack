"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import ProposalWorkflow, WaitlistOfferWorkflow

__all__ = ["ProposalWorkflow", "WaitlistOfferWorkflow"]

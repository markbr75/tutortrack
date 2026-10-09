"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import DisputeWorkflow, PaymentCollectionWorkflow

__all__ = ["DisputeWorkflow", "PaymentCollectionWorkflow"]

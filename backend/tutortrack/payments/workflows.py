"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import (
    BankFeedSyncWorkflow,
    DisputeWorkflow,
    PaymentCollectionWorkflow,
    ProviderMigrationWorkflow,
)

__all__ = [
    "BankFeedSyncWorkflow",
    "DisputeWorkflow",
    "PaymentCollectionWorkflow",
    "ProviderMigrationWorkflow",
]

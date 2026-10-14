"""Workflows defined by this app (autodiscovered by the worker)."""

from .processes import AffiliateStatementRunWorkflow, ReferralRewardWorkflow, ReviewRequestWorkflow

__all__ = ["AffiliateStatementRunWorkflow", "ReferralRewardWorkflow", "ReviewRequestWorkflow"]

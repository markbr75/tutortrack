"""Activities defined by this app (autodiscovered by the worker)."""

from .processes import (
    convert_referral,
    expire_referral,
    issue_monthly_statements,
    referral_milestone_reached,
    referral_state,
    reward_referral,
)

__all__ = [
    "convert_referral",
    "expire_referral",
    "issue_monthly_statements",
    "referral_milestone_reached",
    "referral_state",
    "reward_referral",
]

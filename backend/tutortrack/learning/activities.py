"""Activities defined by this app (autodiscovered by the worker)."""

from .processes import (
    homework_overdue,
    homework_state,
    loan_notice,
    loan_overdue,
    loan_status,
    remind_homework,
    remind_loan,
)

__all__ = [
    "homework_overdue",
    "homework_state",
    "loan_notice",
    "loan_overdue",
    "loan_status",
    "remind_homework",
    "remind_loan",
]

"""Activities defined by this app (autodiscovered by the worker)."""

from .processes import deliver_report, fail_report, generate_report

__all__ = ["deliver_report", "fail_report", "generate_report"]

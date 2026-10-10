"""Activities defined by this app (autodiscovered by the worker)."""

from .processes import attempt_delivery, give_up_delivery

__all__ = ["attempt_delivery", "give_up_delivery"]

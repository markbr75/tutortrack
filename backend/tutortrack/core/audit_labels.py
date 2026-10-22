"""Human labels for audit entries: the action, the record type and the record itself.

``AuditEntry.object_repr`` is captured at write time: it is what the record was called when
it changed, the audit search matches it, and it outlives the record. ``audit.record`` takes
it from ``display_repr`` below, so models without a ``__str__`` get "Refund #3b974e" rather
than Django's "Refund object (01a…)".

The labels the API adds (``action_label``, ``record_type_label``, ``record_label``) are
computed at read time. The table is append-only (a trigger blocks UPDATE), so rows written
before a model had a ``__str__`` can only be made readable on the way out, and labels follow
the reader's language instead of the writer's.
"""

from __future__ import annotations

import contextlib
import re
from typing import Any

from django.apps import apps
from django.db import models
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _

# Django's default ``Model.__str__``: "<ClassName> object (<pk>)".
DEFAULT_REPR = re.compile(r"^\w+ object \((?P<pk>[^()]*)\)$")

# Fields that name a record without naming a person: document numbers ("CN-0007"). Only
# used for models without a ``__str__``; names, titles and references can hold a person's
# name or bank text, so those models get a short id instead.
_NAMING_FIELDS = ("number",)

# Every action code services write (``audit.record(obj, "<code>")`` or
# ``audit.track(obj, action="<code>")``). ``test_audit_labels`` scans the code for new ones.
ACTION_LABELS: dict[str, Any] = {
    "accept": _("Accepted"),
    "account_deleted": _("Account deleted"),
    "achieve": _("Achieved"),
    "activate": _("Activated"),
    "active": _("Resumed"),
    "add_student": _("Student added"),
    "answer": _("Answered"),
    "apply_credit": _("Credit applied"),
    "approve": _("Approved"),
    "approve_erasure": _("Erasure approved"),
    "approve_export": _("Export approved"),
    "archive": _("Archived"),
    "assess": _("Assessed"),
    "assign": _("Assigned"),
    "attendance": _("Attendance recorded"),
    "auto_disable": _("Turned off automatically"),
    "backfill": _("Backfilled"),
    "bank_file": _("Bank file created"),
    "billing_split": _("Billing split changed"),
    "billing_status": _("Billing status changed"),
    "block": _("Blocked"),
    "book_trial": _("Trial booked"),
    "breaks": _("Breaks changed"),
    "calendar_restored": _("Calendar restored"),
    "cancel": _("Cancelled"),
    "cancel_backfill": _("Backfill cancelled"),
    "cancel_requested": _("Cancellation requested"),
    "cancel_signature": _("Signature request cancelled"),
    "cancelled": _("Cancelled"),
    "certificate": _("Certificate updated"),
    "change_pin": _("PIN changed"),
    "change_plan": _("Plan changed"),
    "check": _("Checked"),
    "check_out": _("Checked out"),
    "choose": _("Chosen"),
    "choose_plan": _("Plan chosen"),
    "classify": _("Classified"),
    "close": _("Closed"),
    "close_by_platform": _("Closed by the platform"),
    "compile": _("Compiled"),
    "complete": _("Completed"),
    "completed": _("Completed"),
    "compliance_documents_requested": _("Compliance documents requested"),
    "compliance_override": _("Compliance overridden"),
    "confirm": _("Confirmed"),
    "conflict": _("Released after a clash"),
    "connect": _("Connected"),
    "consume": _("Used"),
    "convert": _("Converted"),
    "create": _("Created"),
    "created": _("Created"),
    "customer_notice": _("Customer notice sent"),
    "deactivate": _("Deactivated"),
    "decline": _("Declined"),
    "declined": _("Declined"),
    "delete": _("Deleted"),
    "deliver": _("Delivered"),
    "disable": _("Turned off"),
    "discard": _("Discarded"),
    "disconnect": _("Disconnected"),
    "dismiss": _("Dismissed"),
    "duplicate": _("Duplicated"),
    "edit": _("Edited"),
    "email_change": _("Email changed"),
    "email_change_requested": _("Email change requested"),
    "enable": _("Turned on"),
    "end": _("Ended"),
    "ended": _("Ended"),
    "erase": _("Erased"),
    "erase_financial": _("Financial records erased"),
    "erasure_blocked": _("Erasure blocked"),
    "error": _("Error"),
    "escalate": _("Escalated"),
    "excuse": _("Excused"),
    "execute": _("Run"),
    "expire": _("Expired"),
    "expired": _("Expired"),
    "export": _("Exported"),
    "export_requested": _("Export requested"),
    "extend": _("Extended"),
    "extend_trial": _("Trial extended"),
    "fail": _("Failed"),
    "failed": _("Failed"),
    "finalise": _("Finalised"),
    "finish": _("Finished"),
    "finish_now": _("Finished early"),
    "flag": _("Flagged"),
    "generate": _("Generated"),
    "gl_export": _("Ledger exported"),
    "grade": _("Graded"),
    "guardian_invited": _("Guardian invited"),
    "hide": _("Hidden"),
    "hold": _("Held"),
    "ignore": _("Ignored"),
    "impersonation_end": _("Impersonation ended"),
    "impersonation_start": _("Impersonation started"),
    "import": _("Imported"),
    "include_restricted": _("Restricted tutors included"),
    "initiated": _("Started"),
    "invite": _("Invited"),
    "invite_tutors": _("Tutors invited"),
    "issue": _("Issued"),
    "item_done": _("Item done"),
    "ledger_adjustment": _("Ledger adjusted"),
    "link_portal_user": _("Portal login linked"),
    "link_tutor": _("Tutor linked"),
    "link_user": _("Login linked"),
    "load_demo_data": _("Sample data loaded"),
    "login": _("Signed in"),
    "lose": _("Marked lost"),
    "lost": _("Lost"),
    "map": _("Mapped"),
    "mastery": _("Mastery updated"),
    "match": _("Matched"),
    "merge": _("Merged"),
    "merged_into": _("Merged into another record"),
    "message": _("Message"),
    "milestone": _("Milestone updated"),
    "milestones": _("Milestones changed"),
    "missed": _("Marked missed"),
    "move": _("Moved"),
    "moved_by_merge": _("Moved by a merge"),
    "new_version": _("New version"),
    "offer": _("Offered"),
    "onboarding_complete": _("Onboarding completed"),
    "onboarding_step": _("Onboarding step done"),
    "open": _("Opened"),
    "opening_balance": _("Opening balance set"),
    "overdue": _("Became overdue"),
    "override_policy": _("Policy overridden"),
    "paid": _("Paid"),
    "past_due": _("Became past due"),
    "pause": _("Paused"),
    "paused": _("Paused"),
    "pay": _("Paid"),
    "payment_recovered": _("Payment recovered"),
    "plan": _("Planned"),
    "platform_flag": _("Flagged by the platform"),
    "platform_note": _("Platform note added"),
    "platform_set_plan": _("Plan set by the platform"),
    "publish": _("Published"),
    "publish_testimonial": _("Testimonial published"),
    "quarantine": _("Quarantined"),
    "questions": _("Questions changed"),
    "reactivate": _("Reactivated"),
    "read": _("Viewed"),
    "ready": _("Ready"),
    "reallocate": _("Reallocated"),
    "reauthenticate": _("Signed in again"),
    "reconciled": _("Reconciled"),
    "reconnect": _("Reconnected"),
    "recovered": _("Recovered"),
    "redact": _("Redacted"),
    "redeem": _("Redeemed"),
    "redeliver": _("Sent again"),
    "refresh": _("Refreshed"),
    "regenerate": _("Regenerated"),
    "register": _("Registered"),
    "reject": _("Rejected"),
    "rejected": _("Rejected"),
    "rejoin": _("Rejoined"),
    "release": _("Released"),
    "remind": _("Reminder sent"),
    "remove": _("Removed"),
    "remove_from_pay_run": _("Removed from the pay run"),
    "reopen": _("Reopened"),
    "replace": _("Replaced"),
    "reporting_rebuild": _("Reports rebuilt"),
    "reprice": _("Repriced"),
    "request_signature": _("Signature requested"),
    "resend": _("Sent again"),
    "reset": _("Reset"),
    "resolve": _("Resolved"),
    "respond": _("Responded"),
    "restart": _("Restarted"),
    "restore": _("Restored"),
    "resume": _("Resumed"),
    "retry": _("Retried"),
    "return": _("Returned"),
    "revenue_share_reported": _("Revenue share reported"),
    "review": _("Reviewed"),
    "reviewed": _("Reviewed"),
    "revoke": _("Revoked"),
    "revoke_access": _("Access revoked"),
    "reward": _("Rewarded"),
    "rollback": _("Rolled back"),
    "rolled_back": _("Rolled back"),
    "rotate": _("Rotated"),
    "rotate_secret": _("Secret rotated"),
    "save": _("Saved"),
    "schedule": _("Scheduled"),
    "schedule_plan": _("Plan change scheduled"),
    "select": _("Selected"),
    "self_billing_agreed": _("Self-billing agreed"),
    "send": _("Sent"),
    "send_test_event": _("Test event sent"),
    "set": _("Set"),
    "set_availability": _("Availability changed"),
    "set_subjects": _("Subjects changed"),
    "setup_checklist_completed": _("Setup checklist completed"),
    "setup_checklist_dismissed": _("Setup checklist dismissed"),
    "share": _("Shared"),
    "sign": _("Signed"),
    "skip": _("Skipped"),
    "snooze": _("Snoozed"),
    "split": _("Split"),
    "start": _("Started"),
    "status": _("Status changed"),
    "status_change": _("Status changed"),
    "step_done": _("Step done"),
    "submit": _("Submitted"),
    "subscribe": _("Subscribed"),
    "supersede": _("Superseded"),
    "support_access": _("Support access"),
    "suspend": _("Suspended"),
    "switch": _("Switched"),
    "switched": _("Switched"),
    "tag": _("Tagged"),
    "tax_identity": _("Tax details changed"),
    "template_error": _("Template error"),
    "terminate": _("Terminated"),
    "transfer": _("Transferred"),
    "trial_converted": _("Trial converted"),
    "trial_expired": _("Trial expired"),
    "trial_outcome": _("Trial outcome recorded"),
    "unapprove": _("Approval withdrawn"),
    "unarchive": _("Unarchived"),
    "unlink_portal_user": _("Portal login unlinked"),
    "unpublish": _("Unpublished"),
    "unshare": _("Unshared"),
    "untag": _("Tag removed"),
    "update": _("Updated"),
    "updated": _("Updated"),
    "update_settings": _("Settings changed"),
    "upload": _("Uploaded"),
    "verify": _("Verified"),
    "void": _("Voided"),
    "waive": _("Waived"),
    "waiting": _("Waiting"),
    "wipe_demo_data": _("Sample data removed"),
    "withdraw": _("Withdrawn"),
    "write_off": _("Written off"),
}


def humanise(code: str) -> str:
    """``"status_change"`` → ``"Status change"``: the fallback for codes without a label."""
    words = re.sub(r"[._]+", " ", code).strip()
    return capfirst(words) or code


def action_label(code: str) -> str:
    label = ACTION_LABELS.get(code)
    return str(label) if label is not None else humanise(code)


def _model(object_type: str) -> type[models.Model] | None:
    try:
        return apps.get_model(object_type)
    except (LookupError, ValueError):
        return None


def record_type_label(object_type: str) -> str:
    """``"scheduling.lessonseries"`` → ``"Lesson series"`` (the model's verbose name)."""
    model = _model(object_type)
    if model is None:
        return humanise(object_type.rsplit(".", 1)[-1])
    return str(capfirst(model._meta.verbose_name))


def short_id(object_id: Any) -> str:
    """The tail of an id: UUIDv7 ids share their time-ordered head, so the tail tells
    records apart (``"01a15826-…-350c023b974e"`` → ``"#3b974e"``)."""
    text = str(object_id).replace("-", "")
    return f"#{text[-6:]}" if text else ""


def _fallback(type_label: str, object_id: Any) -> str:
    return f"{type_label} {short_id(object_id)}".strip()


def display_repr(instance: models.Model) -> str:
    """What ``audit.record`` stores as ``object_repr``: the model's own ``__str__`` when it
    has one, else its type plus its document number or a short id."""
    if type(instance).__str__ is not models.Model.__str__:
        with contextlib.suppress(Exception):  # a label must never break the write it records
            return str(instance)
    sensitive = set(getattr(instance, "audit_sensitive_fields", ()))
    names = {f.name for f in instance._meta.concrete_fields}
    type_label = str(capfirst(instance._meta.verbose_name))
    for name in _NAMING_FIELDS:
        if name in names and name not in sensitive:
            value = getattr(instance, name, "")
            if isinstance(value, str) and value.strip():
                return f"{type_label} {value.strip()}"
    return _fallback(type_label, instance.pk)


def record_label(object_type: str, object_id: Any, object_repr: str) -> str:
    """``object_repr`` as recorded, except Django's default "Charge object (…)" (rows written
    before the model had a ``__str__``) and blanks, which become "Charge #3b974e"."""
    if object_repr and not DEFAULT_REPR.match(object_repr):
        return object_repr
    return _fallback(record_type_label(object_type), object_id)

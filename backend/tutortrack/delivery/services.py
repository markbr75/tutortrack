"""Lesson delivery writes (E09): completion with attendance, policy-driven cancellation,
makeup credits, report templates and lesson reports. Lesson state itself is written by
scheduling's services; this module decides the outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import QuerySet
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.time import now
from tutortrack.scheduling import services as scheduling
from tutortrack.scheduling.models import Lesson, LessonAttendee
from tutortrack.tenancy.settings_service import get_setting

from . import balance, events, policies, templates
from .models import (
    CancellationPolicy,
    CancellationRecord,
    LessonReport,
    LessonReportComment,
    MakeupCredit,
    ReportTemplate,
    ReportTemplateVersion,
)


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


def _setting(key: str, lesson: Lesson | None = None) -> Any:
    return get_setting(key, branch=lesson.branch if lesson is not None else None)


# --- completion ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class AttendanceRow:
    attendee_id: Any
    outcome: str
    late_minutes: int | None = None


def completion_opens_at(lesson: Lesson) -> datetime:
    if _setting("delivery.completion_opens", lesson) == "near_end":
        minutes = int(_setting("delivery.early_completion_minutes", lesson))
        return max(lesson.start, lesson.end - timedelta(minutes=minutes))
    return lesson.start


def _attendance_inputs(
    lesson: Lesson, rows: list[AttendanceRow] | None, policy: policies.ResolvedPolicy
) -> tuple[list[scheduling.AttendanceInput], Decimal]:
    given = {str(r.attendee_id): r for r in rows or []}
    known = {str(a.pk) for a in lesson.attendees.all()}
    if set(given) - known:
        raise _invalid("attendance", _("That student isn't in this lesson."))
    inputs: list[scheduling.AttendanceInput] = []
    for attendee in lesson.attendees.order_by("created_at", "id"):
        row = given.get(str(attendee.pk))
        # An absence notice given beforehand stays unless the register says otherwise.
        expected = attendee.outcome if lesson.status == Lesson.Status.PLANNED else ""
        outcome = row.outcome if row else (expected or LessonAttendee.Outcome.PRESENT)
        if outcome not in LessonAttendee.Outcome.values:
            raise _invalid("attendance", _("Unknown attendance outcome."))
        charge, _pay = policies.attendance_percents(policy, outcome)
        late = row.late_minutes if row and outcome == LessonAttendee.Outcome.LATE else None
        inputs.append(scheduling.AttendanceInput(attendee.pk, outcome, charge, late))
    pay = policies.tutor_pay_percent(policy, [i.outcome for i in inputs])
    return inputs, pay


def _check_balance(lesson: Lesson, inputs: list[scheduling.AttendanceInput]) -> None:
    by_id = {str(a.pk): a for a in lesson.attendees.select_related("client")}
    charges = [(by_id[str(i.attendee_id)], i.charge_percent) for i in inputs if i.charge_percent]
    shortfalls = balance.guard().shortfalls(lesson, charges)
    if not shortfalls:
        return
    with transaction.atomic():
        publish(
            events.LessonCompletionBlocked(
                subject_id=lesson.pk, client_ids=[s.client_id for s in shortfalls]
            ),
            branch_id=lesson.branch_id,
        )
    names = ", ".join(s.client_name for s in shortfalls)
    raise BusinessRuleViolation(
        _("%(names)s needs to top up before this lesson can be completed.") % {"names": names},
        extra={
            "code": "insufficient_balance",
            "shortfalls": [
                {
                    "client": s.client_id,
                    "available": s.available.to_dict(),
                    "needed": s.needed.to_dict(),
                }
                for s in shortfalls
            ],
        },
    )


def complete_lesson(
    lesson: Lesson,
    *,
    user: Any = None,
    attendance: list[AttendanceRow] | None = None,
    actual_start: datetime | None = None,
    actual_end: datetime | None = None,
    override_balance: bool = False,
    auto: bool = False,
) -> Lesson:
    """FR-09-1: complete with attendance; the policy maps outcomes to charge/pay shares.
    Blocks (unless ``override_balance``) when a prepaid client would go below their limit."""
    policy = policies.resolve(lesson)
    inputs, pay = _attendance_inputs(lesson, attendance, policy)
    if lesson.status == Lesson.Status.PLANNED and not override_balance:
        _check_balance(lesson, inputs)
    with transaction.atomic():
        scheduling.complete_lesson(
            lesson,
            attendance=inputs,
            pay_percent=pay,
            actual_start=actual_start,
            actual_end=actual_end,
            reprice_actual=bool(_setting("delivery.bill_actual_duration", lesson)),
            recorded_by=user,
            auto=auto,
            earliest=completion_opens_at(lesson),
        )
        request_reports(lesson)
    return lesson


def record_attendance(lesson: Lesson, rows: list[AttendanceRow], *, user: Any = None) -> Lesson:
    """Correct outcomes after completion; unchanged attendees keep theirs."""
    policy = policies.resolve(lesson)
    given = {str(r.attendee_id): r for r in rows}
    merged = [
        given.get(str(a.pk))
        or AttendanceRow(a.pk, a.outcome or LessonAttendee.Outcome.PRESENT, a.late_minutes)
        for a in lesson.attendees.all()
    ]
    merged += [r for key, r in given.items() if key not in {str(m.attendee_id) for m in merged}]
    inputs, _pay = _attendance_inputs(lesson, merged, policy)
    return scheduling.record_attendance(lesson, inputs, recorded_by=user)


# --- cancellation -------------------------------------------------------------------------------


@dataclass
class CancelResult:
    decision: policies.CancellationDecision
    charge_percent: Decimal
    pay_percent: Decimal
    lesson: Lesson | None = None
    record: CancellationRecord | None = None
    makeup_credits: list[MakeupCredit] = field(default_factory=list)
    following_cancelled: int = 0


def _free_used_this_month(lesson: Lesson, at: datetime) -> int:
    clients = [a.client_id for a in lesson.attendees.all()]
    local = at.astimezone(ZoneInfo(lesson.timezone))
    month_start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (
        CancellationRecord.objects.filter(
            kind=CancellationRecord.Kind.FREE,
            created_at__gte=month_start,
            lesson__attendees__client_id__in=clients,
        )
        .values("lesson_id")
        .distinct()
        .count()
    )


def cancel_lesson(
    lesson: Lesson,
    *,
    user: Any = None,
    cancelled_by: str,
    reason: str = "",
    notify: bool = True,
    override: dict[str, Any] | None = None,
    scope: str = "this",
    preview: bool = False,
) -> CancelResult:
    """FR-09-3. ``override`` = ``{"charge_percent", "pay_percent", "reason"}`` (permission
    checked by the caller; audited). ``scope="following"`` also ends the lesson's series
    (the student is stopping): later lessons are cancelled without charge."""
    if lesson.status != Lesson.Status.PLANNED:
        raise BusinessRuleViolation(_("Only planned lessons can be cancelled."))
    if scope == "following" and lesson.series_id is None:
        raise _invalid("scope", _("This lesson isn't part of a series."))
    at = now()
    decision = policies.evaluate_cancellation(
        lesson,
        cancelled_by=cancelled_by,
        at=at,
        free_used_this_month=_free_used_this_month(lesson, at),
    )
    charge, pay = decision.charge_percent, decision.pay_percent
    if override:
        charge = policies._percent(override.get("charge_percent", charge))
        pay = policies._percent(override.get("pay_percent", pay))
    result = CancelResult(decision, charge, pay)
    if preview:
        return result
    with transaction.atomic():
        scheduling.cancel_lesson(
            lesson,
            reason=reason,
            notify=notify,
            cancelled_by=cancelled_by,
            charge_percent=charge,
            pay_percent=pay,
            policy_kind=decision.kind,
            recorded_by=user,
        )
        record = CancellationRecord.objects.create(
            lesson=lesson,
            cancelled_by_type=cancelled_by,
            cancelled_by_user=user,
            reason=reason[:300],
            notice_minutes=decision.notice_minutes,
            kind=decision.kind,
            policy=decision.policy.policy,
            policy_snapshot=decision.policy.snapshot(),
            charge_percent=charge,
            pay_percent=pay,
            overridden=bool(override),
            override_reason=str((override or {}).get("reason", ""))[:300],
            makeup_credit_issued=decision.makeup_credit,
        )
        audit.record_create(record)
        if override:
            audit.record(
                record,
                "override_policy",
                {
                    "charge_percent": [str(decision.charge_percent), str(charge)],
                    "pay_percent": [str(decision.pay_percent), str(pay)],
                },
            )
        if decision.makeup_credit:
            result.makeup_credits = [
                issue_makeup_credit(lesson, attendee, days=decision.makeup_valid_days)
                for attendee in lesson.attendees.select_related("student")
            ]
        if scope == "following" and lesson.series is not None and lesson.occurrence_date:
            result.following_cancelled = scheduling.end_series(
                lesson.series, after=lesson.occurrence_date, reason=reason
            )
    result.lesson, result.record = lesson, record
    return result


def notify_absence(lesson: Lesson, student: Any, *, note: str = "", user: Any = None) -> Any:
    """A family reports that a student will miss a lesson (FR-15-4). A lesson only for
    them is cancelled by the client (the policy decides any fee); in a group lesson the
    student is marked absent-notified with the policy's charge."""
    attendee = lesson.attendees.filter(student=student).first()
    if attendee is None:
        raise _invalid("student", _("That student isn't in this lesson."))
    if lesson.status != Lesson.Status.PLANNED or lesson.end <= now():
        raise BusinessRuleViolation(_("This lesson can no longer be changed."))
    if lesson.attendees.count() == 1:
        return cancel_lesson(lesson, user=user, cancelled_by="client", reason=note or _("Absent"))
    policy = policies.resolve(lesson)
    charge, _pay = policies.attendance_percents(policy, LessonAttendee.Outcome.ABSENT_NOTIFIED)
    return scheduling.set_expected_absence(
        lesson, attendee, charge_percent=charge, note=note, recorded_by=user
    )


# --- policies -----------------------------------------------------------------------------------


@transaction.atomic
def save_policy(
    *,
    name: str,
    scope_type: str,
    scope_id: Any = None,
    rules: dict[str, Any] | None = None,
    policy: CancellationPolicy | None = None,
) -> CancellationPolicy:
    """Create a policy, or a new version of ``policy`` (the old one is kept inactive)."""
    if scope_type not in CancellationPolicy.Scope.values:
        raise _invalid("scope_type", _("Unknown policy scope."))
    if (scope_type == CancellationPolicy.Scope.ORGANISATION) != (scope_id is None):
        raise _invalid("scope_id", _("Choose what this policy applies to."))
    cleaned = policies.clean_rules(rules)
    version = 1
    if policy is not None:
        if (policy.scope_type, policy.scope_id) != (scope_type, scope_id):
            raise _invalid("scope_type", _("Create a new policy to change what it applies to."))
        version = policy.version + 1
        CancellationPolicy.objects.filter(pk=policy.pk).update(active=False)
        audit.record(policy, "supersede")
    elif CancellationPolicy.objects.filter(
        active=True, scope_type=scope_type, scope_id=scope_id
    ).exists():
        raise _invalid("scope_id", _("There's already a policy for this."))
    created = CancellationPolicy.objects.create(
        name=name,
        scope_type=scope_type,
        scope_id=scope_id,
        rules=cleaned,
        version=version,
        previous=policy,
    )
    audit.record_create(created)
    return created


@transaction.atomic
def delete_policy(policy: CancellationPolicy) -> None:
    CancellationPolicy.objects.filter(pk=policy.pk).update(active=False)
    audit.record(policy, "deactivate")


# --- makeup credits -----------------------------------------------------------------------------


def issue_makeup_credit(lesson: Lesson, attendee: LessonAttendee, *, days: int) -> MakeupCredit:
    credit, created = MakeupCredit.objects.get_or_create(
        source_lesson=lesson,
        student=attendee.student,
        defaults={"client_id": attendee.client_id, "expires_at": now() + timedelta(days=days)},
    )
    if created:
        audit.record_create(credit)
        publish(
            events.MakeupCreditIssued(
                subject_id=credit.pk,
                student_id=str(credit.student_id),
                source_lesson_id=str(lesson.pk),
                expires_at=credit.expires_at.isoformat(),
            )
        )
    return credit


@transaction.atomic
def consume_makeup_credit(credit: MakeupCredit, lesson: Lesson) -> MakeupCredit:
    """Use a credit for a makeup lesson: that student is not charged for it (E10)."""
    credit = MakeupCredit.objects.select_for_update().get(pk=credit.pk)
    if credit.status_at(now()) != MakeupCredit.Status.AVAILABLE:
        raise BusinessRuleViolation(_("This makeup credit has been used or has expired."))
    if lesson.pk == credit.source_lesson_id or lesson.status == Lesson.Status.CANCELLED:
        raise _invalid("lesson", _("Choose the makeup lesson."))
    if not lesson.attendees.filter(student_id=credit.student_id).exists():
        raise _invalid("lesson", _("The student isn't booked on that lesson."))
    if MakeupCredit.objects.filter(
        consumed_by_lesson=lesson, student_id=credit.student_id
    ).exists():
        raise _invalid("lesson", _("That lesson already uses a makeup credit."))
    with audit.track(credit, action="consume"):
        credit.consumed_by_lesson = lesson
        credit.consumed_at = now()
        credit.save(update_fields=["consumed_by_lesson", "consumed_at", "updated_at"])
    publish(
        events.MakeupCreditConsumed(
            subject_id=credit.pk, student_id=str(credit.student_id), lesson_id=str(lesson.pk)
        )
    )
    return credit


@transaction.atomic
def extend_makeup_credit(credit: MakeupCredit, *, until: datetime) -> MakeupCredit:
    if credit.consumed_by_lesson_id or credit.voided_at:
        raise BusinessRuleViolation(_("Only unused credits can be extended."))
    if until <= now():
        raise _invalid("until", _("Choose a date in the future."))
    with audit.track(credit, action="extend"):
        credit.expires_at = until
        credit.save(update_fields=["expires_at", "updated_at"])
    return credit


@transaction.atomic
def void_makeup_credit(credit: MakeupCredit, *, note: str = "") -> MakeupCredit:
    if credit.consumed_by_lesson_id:
        raise BusinessRuleViolation(_("This credit has already been used."))
    with audit.track(credit, action="void"):
        credit.voided_at = now()
        credit.note = note[:300]
        credit.save(update_fields=["voided_at", "note", "updated_at"])
    publish(events.MakeupCreditVoided(subject_id=credit.pk, student_id=str(credit.student_id)))
    return credit


# --- report templates ---------------------------------------------------------------------------


def _set_assignments(template: ReportTemplate, assignments: dict[str, Any]) -> None:
    for name in ("services", "subjects", "jobs"):
        if name in assignments and assignments[name] is not None:
            getattr(template, name).set(assignments[name])


@transaction.atomic
def create_template(
    *,
    name: str,
    fields: Any,
    description: str = "",
    is_default: bool = False,
    **assignments: Any,
) -> ReportTemplate:
    cleaned = templates.clean_fields(fields)
    if is_default:
        ReportTemplate.objects.filter(is_default=True).update(is_default=False)
    template = ReportTemplate.objects.create(
        name=name, description=description, is_default=is_default
    )
    version = ReportTemplateVersion.objects.create(template=template, version=1, fields=cleaned)
    template.current_version = version
    template.save(update_fields=["current_version", "updated_at"])
    _set_assignments(template, assignments)
    audit.record_create(template)
    return template


@transaction.atomic
def update_template(template: ReportTemplate, **changes: Any) -> ReportTemplate:
    """Changing ``fields`` adds a version; reports already written keep theirs."""
    fields = changes.pop("fields", None)
    assignments: dict[str, Any] = {
        k: changes.pop(k) for k in ("services", "subjects", "jobs") if k in changes
    }
    with audit.track(template, action="update"):
        if changes.get("is_default"):
            ReportTemplate.objects.filter(is_default=True).exclude(pk=template.pk).update(
                is_default=False
            )
        for key, value in changes.items():
            setattr(template, key, value)
        if fields is not None:
            cleaned = templates.clean_fields(fields)
            current = template.current_version
            if current is None or current.fields != cleaned:
                number = (current.version if current else 0) + 1
                template.current_version = ReportTemplateVersion.objects.create(
                    template=template, version=number, fields=cleaned
                )
        template.save()
    _set_assignments(template, assignments)
    return template


@transaction.atomic
def archive_template(template: ReportTemplate) -> ReportTemplate:
    with audit.track(template, action="archive"):
        template.archived_at = now()
        template.is_default = False
        template.save(update_fields=["archived_at", "is_default", "updated_at"])
    return template


def ensure_default_template() -> ReportTemplate:
    existing = ReportTemplate.objects.filter(is_default=True, archived_at__isnull=True).first()
    if existing is not None:
        return existing
    return create_template(name=_("Simple"), fields=templates.simple_fields(), is_default=True)


def resolve_template(lesson: Lesson) -> ReportTemplate:
    """Job → service → subject → organisation default (FR-09-4)."""
    live: QuerySet[ReportTemplate] = ReportTemplate.objects.filter(
        archived_at__isnull=True, current_version__isnull=False
    )
    checks: list[QuerySet[ReportTemplate]] = []
    if lesson.job_id:
        checks.append(live.filter(jobs=lesson.job_id))
    checks.append(live.filter(services=lesson.service_id))
    if lesson.service.subject_id:
        checks.append(live.filter(subjects=lesson.service.subject_id))
    for qs in checks:
        template = qs.order_by("name").first()
        if template is not None:
            return template
    return ensure_default_template()


# --- reports ------------------------------------------------------------------------------------


def _due_at(lesson: Lesson) -> datetime:
    return lesson.end + timedelta(hours=int(_setting("delivery.report_due_hours", lesson)))


def _report_event(cls: type[events._ReportEvent], report: LessonReport, **data: Any) -> None:
    publish(
        cls(
            subject_id=report.pk,
            lesson_id=str(report.lesson_id),
            tutor_id=str(report.tutor_id),
            **data,
        ),
        branch_id=report.lesson.branch_id,
    )


def _new_report(lesson: Lesson, tutor_id: Any) -> tuple[LessonReport, bool]:
    template = resolve_template(lesson)
    if template.current_version is None:  # resolve_template only returns versioned ones
        raise BusinessRuleViolation(_("The report template has no fields."))
    return LessonReport.objects.get_or_create(
        lesson=lesson,
        tutor_id=tutor_id,
        defaults={"template_version": template.current_version, "due_at": _due_at(lesson)},
    )


def request_reports(lesson: Lesson) -> list[LessonReport]:
    """After completion: one report per tutor when reports are required (FR-09-7)."""
    if not _setting("delivery.report_required", lesson):
        return []
    out = []
    for link in lesson.tutors.all():
        report, _created = _new_report(lesson, link.tutor_id)
        if not report.is_written and report.due_at != _due_at(lesson):
            report.due_at = _due_at(lesson)
            report.save(update_fields=["due_at", "updated_at"])
        if not report.is_written:
            _report_event(events.LessonReportRequested, report, due_at=report.due_at.isoformat())
        out.append(report)
    return out


@transaction.atomic
def open_report(lesson: Lesson, tutor: Any) -> LessonReport:
    """The tutor's report for a lesson, created as ``pending`` if needed."""
    if lesson.status == Lesson.Status.CANCELLED:
        raise BusinessRuleViolation(_("Cancelled lessons don't have reports."))
    if not lesson.tutors.filter(tutor=tutor).exists():
        raise _invalid("tutor", _("That tutor isn't teaching this lesson."))
    report, _created = _new_report(lesson, tutor.pk)
    return report


def _check_editable(report: LessonReport, *, can_edit_any: bool) -> None:
    if can_edit_any or not report.is_written:
        return
    window = int(_setting("delivery.report_edit_window_hours", report.lesson))
    if report.submitted_at and now() > report.submitted_at + timedelta(hours=window):
        raise PermissionDenied(_("The edit window for this report has closed."))


@transaction.atomic
def save_draft(
    report: LessonReport, answers: Any, *, user: Any = None, can_edit_any: bool = False
) -> LessonReport:
    _check_editable(report, can_edit_any=can_edit_any)
    cleaned = templates.clean_answers(report.template_version.fields, answers)
    with audit.track(report, action="edit"):
        report.answers = cleaned
        if report.status in {LessonReport.Status.PENDING, LessonReport.Status.RETURNED}:
            report.status = LessonReport.Status.DRAFT
        report.save(update_fields=["answers", "status", "updated_at"])
    return report


@transaction.atomic
def submit_report(
    report: LessonReport, *, user: Any = None, answers: Any = None, can_edit_any: bool = False
) -> LessonReport:
    if answers is not None:
        save_draft(report, answers, user=user, can_edit_any=can_edit_any)
    if report.is_written:
        raise BusinessRuleViolation(_("This report has already been submitted."))
    report.answers = templates.clean_answers(
        report.template_version.fields, report.answers, require=True
    )
    lesson = report.lesson
    with audit.track(report, action="submit"):
        report.status = LessonReport.Status.SUBMITTED
        report.submitted_at = now()
        report.submitted_by = user
        report.pay_held = False
        report.save()
    _report_event(events.LessonReportSubmitted, report)
    if (
        lesson.status == Lesson.Status.PLANNED
        and _setting("delivery.report_submit_completes", lesson)
        and completion_opens_at(lesson) <= now()
    ):
        complete_lesson(lesson, user=user)
        report.refresh_from_db()
    if not _setting("delivery.report_approval_required", lesson) and _setting(
        "delivery.report_auto_share", lesson
    ):
        share_report(report, user=user)
    return report


@transaction.atomic
def approve_report(report: LessonReport, *, user: Any = None) -> LessonReport:
    if report.status != LessonReport.Status.SUBMITTED:
        raise BusinessRuleViolation(_("Only submitted reports can be approved."))
    with audit.track(report, action="approve"):
        report.status = LessonReport.Status.APPROVED
        report.approved_at = now()
        report.approved_by = user
        report.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])
    _report_event(events.LessonReportApproved, report)
    if _setting("delivery.report_auto_share", report.lesson):
        share_report(report, user=user)
    return report


@transaction.atomic
def return_report(report: LessonReport, *, user: Any = None, note: str = "") -> LessonReport:
    if report.status != LessonReport.Status.SUBMITTED:
        raise BusinessRuleViolation(_("Only submitted reports can be returned."))
    with audit.track(report, action="return"):
        report.status = LessonReport.Status.RETURNED
        report.returned_note = note[:500]
        report.submitted_at = None
        report.save(update_fields=["status", "returned_note", "submitted_at", "updated_at"])
    _report_event(events.LessonReportReturned, report, note=note[:500])
    return report


@transaction.atomic
def share_report(report: LessonReport, *, user: Any = None) -> LessonReport:
    if not report.is_written:
        raise BusinessRuleViolation(_("Submit the report before sharing it."))
    if report.status != LessonReport.Status.APPROVED and _setting(
        "delivery.report_approval_required", report.lesson
    ):
        raise BusinessRuleViolation(_("This report needs approval before it is shared."))
    if report.shared_at:
        return report
    with audit.track(report, action="share"):
        report.shared_at = now()
        report.save(update_fields=["shared_at", "updated_at"])
    clients = sorted({str(c) for c in report.lesson.attendees.values_list("client_id", flat=True)})
    _report_event(events.LessonReportShared, report, client_ids=clients)
    return report


@transaction.atomic
def add_comment(
    report: LessonReport, *, user: Any, body: str, visibility: str = "client"
) -> LessonReportComment:
    body = body.strip()
    if not body:
        raise _invalid("body", _("Write a comment."))
    if visibility not in LessonReportComment.Visibility.values:
        raise _invalid("visibility", _("Unknown visibility."))
    comment = LessonReportComment.objects.create(
        report=report,
        author=user,
        author_name=(user.get_full_name() or user.email) if user else _("System"),
        body=body[:5000],
        visibility=visibility,
    )
    audit.record_create(comment)
    _report_event(
        events.LessonReportCommented, report, comment_id=str(comment.pk), visibility=visibility
    )
    return comment


# --- SLA steps (called by the LessonReportSlaWorkflow activities) ---------------------------


@transaction.atomic
def report_due_reminder(report_id: Any, *, dedupe_key: str | None = None) -> bool:
    report = LessonReport.objects.select_related("lesson").filter(pk=report_id).first()
    if report is None or report.is_written:
        return False
    publish(
        events.LessonReportDue(
            subject_id=report.pk,
            lesson_id=str(report.lesson_id),
            tutor_id=str(report.tutor_id),
            due_at=report.due_at.isoformat(),
        ),
        branch_id=report.lesson.branch_id,
        dedupe_key=dedupe_key,
    )
    return True


@transaction.atomic
def mark_report_overdue(report_id: Any, *, dedupe_key: str | None = None) -> bool:
    report = (
        LessonReport.objects.select_for_update().select_related("lesson").filter(pk=report_id)
    ).first()
    if report is None or report.is_written or report.overdue_at:
        return False
    hold = bool(_setting("delivery.hold_pay_overdue_reports", report.lesson))
    with audit.track(report, action="overdue"):
        report.overdue_at = now()
        report.pay_held = hold
        report.save(update_fields=["overdue_at", "pay_held", "updated_at"])
    publish(
        events.LessonReportOverdue(
            subject_id=report.pk,
            lesson_id=str(report.lesson_id),
            tutor_id=str(report.tutor_id),
            pay_held=hold,
        ),
        branch_id=report.lesson.branch_id,
        dedupe_key=dedupe_key,
    )
    return True


@transaction.atomic
def escalate_report(report_id: Any, *, dedupe_key: str | None = None) -> bool:
    """Tell staff: a task for the coordinators' queue (E05) and an event (E13)."""
    from tutortrack.crm import services as crm

    report = (
        LessonReport.objects.select_for_update()
        .select_related("lesson", "tutor")
        .filter(pk=report_id)
        .first()
    )
    if report is None or report.is_written or report.escalated_at:
        return False
    with audit.track(report, action="escalate"):
        report.escalated_at = now()
        report.save(update_fields=["escalated_at", "updated_at"])
    crm.create_task(
        title=_("Overdue lesson report: %(lesson)s (%(tutor)s)")
        % {"lesson": report.lesson.title, "tutor": report.tutor.full_name},
        target_type="delivery.lesson_report",
        target_id=str(report.pk),
        due_at=now() + timedelta(days=1),
    )
    publish(
        events.LessonReportEscalated(
            subject_id=report.pk, lesson_id=str(report.lesson_id), tutor_id=str(report.tutor_id)
        ),
        branch_id=report.lesson.branch_id,
        dedupe_key=dedupe_key,
    )
    return True


# --- unconfirmed lessons ------------------------------------------------------------------------


def nudge_unconfirmed(lesson: Lesson, *, dedupe_key: str | None = None) -> bool:
    if lesson.status != Lesson.Status.PLANNED:
        return False
    with transaction.atomic():
        scheduling.flag_unconfirmed(lesson)
        publish(
            events.LessonUnconfirmed(
                subject_id=lesson.pk,
                tutor_ids=[str(t) for t in lesson.tutors.values_list("tutor_id", flat=True)],
            ),
            branch_id=lesson.branch_id,
            dedupe_key=dedupe_key,
        )
    return True


def handle_unconfirmed(lesson_id: Any, *, dedupe_key: str | None = None) -> str:
    """FR-09-8 step: still planned after N hours → auto-complete (setting) or flag."""
    lesson = Lesson.objects.select_related("branch", "service").filter(pk=lesson_id).first()
    if lesson is None or lesson.status != Lesson.Status.PLANNED:
        return "resolved"
    if _setting("delivery.unconfirmed_action", lesson) == "auto_complete":
        try:
            complete_lesson(lesson, auto=True)
            return "auto_completed"
        except BusinessRuleViolation:
            pass  # e.g. a prepaid client without credit: leave it for staff
    nudge_unconfirmed(lesson, dedupe_key=dedupe_key)
    return "flagged"

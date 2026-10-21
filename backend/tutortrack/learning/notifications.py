"""Messages for learning tools (E21), on the E13 registry: homework to families and
students, hand-ins to tutors, shared resources and progress reports, achieved goals and
library loans."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.comms import catalogue
from tutortrack.comms.catalogue import (
    SAMPLE_BASE,
    client_contacts,
    contact_recipient,
    organisation,
    tenant_link,
    tutor_recipient,
    user_recipient,
)
from tutortrack.comms.defaults import DEFAULTS, SIGN
from tutortrack.comms.registry import Delivery, NotificationType, Recipient, register
from tutortrack.core.time import now


def _people(student: Any) -> list[Recipient]:
    """The student's family (contacts who get reports) and the student's own login."""
    out = [contact_recipient(c) for c in client_contacts(student.client, "receives_reports")]
    if student.user_id and student.user.is_active:
        out.append(user_recipient(student.user))
    return out


def _deliveries(recipients: list[Recipient], extra: dict[str, Any]) -> list[Delivery]:
    seen: set[tuple[str, str]] = set()
    out = []
    for r in recipients:
        if (r.kind, r.id) in seen:
            continue
        seen.add((r.kind, r.id))
        out.append(
            Delivery(
                r,
                {
                    "organisation": organisation(),
                    "recipient": {"name": r.name, "first_name": r.first_name},
                    **extra,
                },
            )
        )
    return out


def load_assignment(pk: Any) -> Any:
    from .models import HomeworkAssignment

    return (
        HomeworkAssignment.objects.select_related(
            "homework__set_by__membership", "student__client", "student__user"
        )
        .filter(pk=pk)
        .first()
    )


def _homework(assignment: Any) -> dict[str, Any]:
    homework = assignment.homework
    return {
        "homework": {
            "title": homework.title,
            "student": assignment.student.first_name,
            "due_at": assignment.due_at,
            "grade": assignment.grade,
            "feedback": assignment.feedback,
            "tutor": homework.set_by.full_name if homework.set_by else "",
            "link": tenant_link(f"/portal/learning/homework/{assignment.pk}"),
        }
    }


def _to_family(assignment: Any) -> list[Delivery]:
    if assignment is None:
        return []
    return _deliveries(_people(assignment.student), _homework(assignment))


def _to_tutor(assignment: Any) -> list[Delivery]:
    if assignment is None or assignment.homework.set_by is None:
        return []
    extra = _homework(assignment)
    extra["homework"]["link"] = tenant_link(f"/portal/tutor/homework/{assignment.pk}")
    return _deliveries([tutor_recipient(assignment.homework.set_by)], extra)


def load_share(pk: Any) -> Any:
    from .models import ResourceShare

    return (
        ResourceShare.objects.select_related("resource", "shared_by", "lesson")
        .filter(pk=pk)
        .first()
    )


def _resource_shared(payload: Any) -> list[Delivery]:
    from tutortrack.people.models import Student

    share, student_ids = payload
    if share is None:
        return []
    recipients: list[Recipient] = []
    for student in Student.objects.filter(pk__in=student_ids).select_related("client", "user"):
        recipients += _people(student)
    link = "/portal/learning?tab=resources"
    lesson = share.lesson
    if lesson is not None and lesson.online and lesson.end > now():
        link = f"/portal/classroom/{lesson.pk}"  # gap G5c (FR-21-8): it's in the room
    return _deliveries(
        recipients,
        {
            "resource": {
                "title": share.resource.title,
                "message": share.message,
                "link": tenant_link(link),
            }
        },
    )


def load_report(pk: Any) -> Any:
    from .models import ProgressReport

    return (
        ProgressReport.objects.select_related("student__client", "student__user")
        .filter(pk=pk)
        .first()
    )


def _progress_shared(report: Any) -> list[Delivery]:
    if report is None:
        return []
    return _deliveries(
        _people(report.student),
        {
            "report": {
                "title": report.title,
                "student": report.student.first_name,
                "link": tenant_link("/portal/learning?tab=progress"),
            }
        },
    )


def _progress_pdf(report: Any) -> list[tuple[str, bytes, str]]:
    from .progress import pdf

    return [(f"progress-report-{report.period_end}.pdf", pdf(report), "application/pdf")]


def load_goal(pk: Any) -> Any:
    from .models import Goal

    return Goal.objects.select_related("student__client", "student__user").filter(pk=pk).first()


def _goal(goal: Any) -> list[Delivery]:
    if goal is None or not goal.visible_to_family:
        return []
    return _deliveries(
        _people(goal.student), {"goal": {"title": goal.title, "student": goal.student.first_name}}
    )


def load_loan(pk: Any) -> Any:
    from .models import Loan

    return (
        Loan.objects.select_related("item", "student__client", "student__user")
        .filter(pk=pk)
        .first()
    )


def _loan(loan: Any) -> list[Delivery]:
    if loan is None:
        return []
    recipients = [contact_recipient(c) for c in client_contacts(loan.student.client)]
    return _deliveries(
        recipients,
        {
            "loan": {
                "item": loan.item.name,
                "student": loan.student.first_name,
                "due_date": loan.due_date.isoformat(),
            }
        },
    )


SAMPLE_HOMEWORK = {
    "title": "Fractions worksheet",
    "student": "Arjun",
    "due_at": "2026-11-03T18:00:00+00:00",
    "grade": "7",
    "feedback": "Great work on equivalent fractions.",
    "tutor": "Nia Adeyemi",
    "link": "https://brightminds.tutortrack.app/portal/learning/homework/1",
}
HOMEWORK_VARS = (
    "homework.title",
    "homework.student",
    "homework.due_at",
    "homework.grade",
    "homework.feedback",
    "homework.tutor",
    "homework.link",
)


def _family_type(key: str, label: Any, **options: Any) -> None:
    register(
        NotificationType(
            key=key,
            label=str(label),
            category="reports",
            audience="client",
            channels=("email", "in_app"),
            default_channels=("email", "in_app"),
            **options,
        )
    )


for _key, _label in (
    ("homework_assigned", _("New homework")),
    ("homework_reminder", _("Homework due soon")),
    ("homework_overdue", _("Homework overdue")),
    ("homework_graded", _("Homework marked")),
):
    _family_type(
        _key,
        _label,
        resolve=_to_family,
        load=load_assignment,
        related_type="learning.homeworkassignment",
        variables=HOMEWORK_VARS,
        sample={**SAMPLE_BASE, "homework": SAMPLE_HOMEWORK},
        link=lambda a: f"/portal/learning/homework/{a.pk}",
    )
register(
    NotificationType(
        key="homework_submitted",
        label=str(_("Homework handed in (to the tutor)")),
        category="reports",
        audience="tutor",
        channels=("email", "in_app"),
        default_channels=("in_app",),
        resolve=_to_tutor,
        load=load_assignment,
        related_type="learning.homeworkassignment",
        variables=HOMEWORK_VARS,
        sample={**SAMPLE_BASE, "homework": SAMPLE_HOMEWORK},
        link=lambda a: f"/portal/tutor/homework/{a.pk}",
    )
)
_family_type(
    "resource_shared",
    _("A resource was shared"),
    resolve=_resource_shared,
    load=lambda pk: None,
    related_type="",
    variables=("resource.title", "resource.message", "resource.link"),
    sample={
        **SAMPLE_BASE,
        "resource": {"title": "Fractions video", "message": "", "link": "https://example.com"},
    },
)
_family_type(
    "progress_report_shared",
    _("Progress report shared"),
    resolve=_progress_shared,
    load=load_report,
    related_type="learning.progressreport",
    variables=("report.title", "report.student", "report.link"),
    sample={
        **SAMPLE_BASE,
        "report": {
            "title": "Autumn term progress",
            "student": "Arjun",
            "link": "https://example.com",
        },
    },
    attachments=_progress_pdf,
)
_family_type(
    "goal_achieved",
    _("A goal was achieved"),
    resolve=_goal,
    load=load_goal,
    related_type="learning.goal",
    variables=("goal.title", "goal.student"),
    sample={**SAMPLE_BASE, "goal": {"title": "Grade 7 in the mock", "student": "Arjun"}},
)
for _key, _label in (
    ("loan_due", _("Library loan due soon")),
    ("loan_overdue", _("Library loan overdue")),
):
    _family_type(
        _key,
        _label,
        resolve=_loan,
        load=load_loan,
        related_type="learning.loan",
        variables=("loan.item", "loan.student", "loan.due_date"),
        sample={
            **SAMPLE_BASE,
            "loan": {"item": "Violin (3/4)", "student": "Maya", "due_date": "2026-11-03"},
        },
    )


# Gap G5c (FR-21-6): scheduled drafts wait for the author's comments; staff get a summary.
def _drafts_to_tutor(payload: Any) -> list[Delivery]:
    tutor, count, period = payload
    return _deliveries(
        [tutor_recipient(tutor)],
        {"drafts": {"count": count, "period": period, "link": tenant_link("/learning")}},
    )


register(
    NotificationType(
        key="progress_reports_drafted",
        label=str(_("Progress reports drafted for you (to the tutor)")),
        category="reports",
        audience="tutor",
        channels=("email", "in_app"),
        default_channels=("email", "in_app"),
        resolve=_drafts_to_tutor,
        load=lambda pk: None,
        related_type="",
        variables=("drafts.count", "drafts.period", "drafts.link"),
        sample={**SAMPLE_BASE, "drafts": {"count": 4, "period": "2026-10", "link": "/"}},
        link=lambda payload: "/learning",
    )
)
register(
    NotificationType(
        key="staff_progress_reports_drafted",
        label=str(_("Progress reports drafted on schedule")),
        category="staff",
        audience="staff",
        channels=("in_app", "email"),
        default_channels=("in_app",),
        resolve=catalogue._alert("learning.progress.approve"),
        load=lambda pk: None,
        related_type="",
        variables=("alert.title", "alert.body", "alert.link"),
        sample=catalogue.SAMPLE_ALERT,
        link=lambda payload: payload[2],
    )
)

DEFAULTS.update(
    {
        ("progress_reports_drafted", "email"): (
            "Progress reports to finish for {{ drafts.period }}",
            "Hello {{ recipient.first_name }},\n\n{{ drafts.count }} progress report(s) for "
            "{{ drafts.period }} have been drafted for your students. Add your comments and "
            "submit them: {{ drafts.link }}" + SIGN,
        ),
        ("progress_reports_drafted", "in_app"): (
            "Progress reports to finish",
            "{{ drafts.count }} for {{ drafts.period }}",
        ),
        ("staff_progress_reports_drafted", "in_app"): ("{{ alert.title }}", "{{ alert.body }}"),
        ("staff_progress_reports_drafted", "email"): (
            "{{ alert.title }}",
            "{{ alert.body }}\n\n{{ alert.link }}" + SIGN,
        ),
    }
)

DEFAULTS.update(
    {
        ("homework_assigned", "email"): (
            "New homework for {{ homework.student }}: {{ homework.title }}",
            "Hello {{ recipient.first_name }},\n\n{{ homework.tutor or 'Your tutor' }} set "
            '{{ homework.title }}, due {{ homework.due_at|datetime("short") }}.\n\n'
            "See it and hand it in: {{ homework.link }}" + SIGN,
        ),
        ("homework_assigned", "in_app"): (
            "New homework: {{ homework.title }}",
            'Due {{ homework.due_at|datetime("short") }}',
        ),
        ("homework_reminder", "email"): (
            "Reminder: {{ homework.title }} is due soon",
            "Hello {{ recipient.first_name }},\n\n{{ homework.title }} is due "
            '{{ homework.due_at|datetime("short") }}: {{ homework.link }}' + SIGN,
        ),
        ("homework_reminder", "in_app"): (
            "{{ homework.title }} is due soon",
            'Due {{ homework.due_at|datetime("short") }}',
        ),
        ("homework_overdue", "email"): (
            "{{ homework.title }} is overdue",
            "Hello {{ recipient.first_name }},\n\n{{ homework.student }}'s homework "
            '{{ homework.title }} was due {{ homework.due_at|datetime("short") }} and hasn\'t '
            "been handed in yet: {{ homework.link }}" + SIGN,
        ),
        ("homework_overdue", "in_app"): (
            "{{ homework.title }} is overdue",
            'It was due {{ homework.due_at|datetime("short") }}',
        ),
        ("homework_graded", "email"): (
            "{{ homework.title }} has been marked",
            "Hello {{ recipient.first_name }},\n\n{{ homework.title }} has been marked"
            "{% if homework.grade %}: {{ homework.grade }}{% endif %}.\n\n"
            "{{ homework.feedback }}\n\n{{ homework.link }}" + SIGN,
        ),
        ("homework_graded", "in_app"): (
            "{{ homework.title }} has been marked",
            "{% if homework.grade %}{{ homework.grade }}{% endif %}",
        ),
        ("homework_submitted", "email"): (
            "{{ homework.student }} handed in {{ homework.title }}",
            "Hello {{ recipient.first_name }},\n\n{{ homework.student }} handed in "
            "{{ homework.title }}. Review it: {{ homework.link }}" + SIGN,
        ),
        ("homework_submitted", "in_app"): (
            "{{ homework.student }} handed in homework",
            "{{ homework.title }}",
        ),
        ("resource_shared", "email"): (
            "New resource: {{ resource.title }}",
            "Hello {{ recipient.first_name }},\n\n{{ resource.title }} has been shared with you."
            "\n\n{{ resource.message }}\n\n{{ resource.link }}" + SIGN,
        ),
        ("resource_shared", "in_app"): (
            "New resource: {{ resource.title }}",
            "{{ resource.message }}",
        ),
        ("progress_report_shared", "email"): (
            "{{ report.title }}",
            "Hello {{ recipient.first_name }},\n\n{{ report.student }}'s progress report is "
            "attached. You can also read it in the portal: {{ report.link }}" + SIGN,
        ),
        ("progress_report_shared", "in_app"): (
            "New progress report for {{ report.student }}",
            "{{ report.title }}",
        ),
        ("goal_achieved", "email"): (
            "{{ goal.student }} achieved a goal",
            "Hello {{ recipient.first_name }},\n\n{{ goal.student }} achieved: {{ goal.title }}."
            + SIGN,
        ),
        ("goal_achieved", "in_app"): ("Goal achieved", "{{ goal.title }}"),
        ("loan_due", "email"): (
            "Please return {{ loan.item }}",
            "Hello {{ recipient.first_name }},\n\n{{ loan.student }} borrowed {{ loan.item }}. "
            "It's due back on {{ loan.due_date }}." + SIGN,
        ),
        ("loan_due", "in_app"): ("{{ loan.item }} is due back soon", "Due {{ loan.due_date }}"),
        ("loan_overdue", "email"): (
            "{{ loan.item }} is overdue",
            "Hello {{ recipient.first_name }},\n\n{{ loan.item }}, borrowed by "
            "{{ loan.student }}, was due back on {{ loan.due_date }}. Please return it as soon "
            "as you can." + SIGN,
        ),
        ("loan_overdue", "in_app"): ("{{ loan.item }} is overdue", "Due {{ loan.due_date }}"),
    }
)

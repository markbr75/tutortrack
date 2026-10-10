"""The recipe library (FR-14-6): ready-made automations installed with one click.

Recipes are platform-defined and live in code (like the plan catalogue). Installing copies
one into the organisation as an ordinary, disabled automation to review and switch on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Recipe:
    key: str
    name: str
    description: str
    trigger_type: str
    trigger_config: dict[str, Any]
    steps: list[dict[str, Any]]
    conditions: dict[str, Any] = field(default_factory=dict)


def _msg(to: list[str], channels: list[str], subject: str, body: str) -> dict[str, Any]:
    return {
        "type": "action",
        "action": "send_message",
        "config": {"to": to, "channels": channels, "subject": subject, "body": body},
    }


def _task(title: str, assignee: str = "owner", hours: int = 24) -> dict[str, Any]:
    return {"type": "action", "action": "create_task",
            "config": {"title": title, "assignee": assignee, "due_in_hours": hours}}  # fmt: skip


def _tag(tag: str) -> dict[str, Any]:
    return {"type": "action", "action": "add_tag", "config": {"tag": tag}}


RECIPES: list[Recipe] = [
    Recipe(
        "new_enquiry", "New enquiry: reply and follow up",
        "Thank the family straight away and give the enquiry's owner a call-back task due "
        "within the hour.",
        "event", {"event": "enquiry.received"},
        [
            _msg(["client"], ["email"], "Thanks for getting in touch",
                 "Hello {{ recipient.first_name }},\n\nThank you for your enquiry. We'll call "
                 "you shortly to talk about what you're looking for."),
            _task("Call {{ enquiry.client.name }} about their enquiry", "owner", 1),
        ],
    ),
    Recipe(
        "trial_follow_up", "Trial lesson: feedback, then chase",
        "A day after a trial lesson, ask how it went and offer packages; if the enquiry is "
        "still open five days later, task someone to call.",
        "event", {"event": "trial_lesson.completed"},
        [
            {"type": "wait", "days": 1},
            _msg(["client"], ["email"], "How was the trial lesson?",
                 "Hello {{ recipient.first_name }},\n\nWe hope the trial lesson went well. "
                 "Reply to this email to book regular lessons or ask about our packages."),
            {"type": "wait", "days": 5},
            {"type": "branch",
             "if": {"field": "enquiry.status", "op": "equals", "value": "open"},
             "then": [_task("Call {{ enquiry.client.name }}: no booking since the trial")],
             "else": []},
        ],
    ),
    Recipe(
        "dormant_students", "No lesson for 30 days: tag and re-engage",
        "Every Monday, tag active students who haven't had a lesson in 30 days as dormant and "
        "email the family.",
        "schedule", {"subject": "student", "frequency": "weekly", "weekday": 0, "time": "08:00"},
        [
            _tag("Dormant"),
            _msg(["client"], ["email"], "We miss {{ student.first_name }}",
                 "Hello {{ recipient.first_name }},\n\nIt's been a while since "
                 "{{ student.first_name }}'s last lesson. Reply to book the next one."),
        ],
        {"all": [
            {"field": "student.status", "op": "equals", "value": "active"},
            {"field": "student.last_lesson_at", "op": "older_than_days", "value": 30},
        ]},
    ),
    Recipe(
        "report_overdue", "Overdue lesson report: nudge, then escalate",
        "Text the tutor when a report is overdue; if it's still not written a day later, task "
        "the job's account manager.",
        "event", {"event": "lesson_report.overdue"},
        [
            _msg(["tutor"], ["sms", "in_app"], "Lesson report overdue",
                 "Please write the report for {{ lesson_report.lesson.title }}."),
            {"type": "wait", "hours": 24},
            {"type": "branch",
             "if": {"field": "lesson_report.status", "op": "in",
                    "value": ["pending", "draft", "returned"]},
             "then": [_task("Chase {{ lesson_report.tutor }} for an overdue report")],
             "else": []},
        ],
    ),
    Recipe(
        "balance_low", "Prepaid balance low: ask for a top-up",
        "Email the family when their prepaid credit runs low.",
        "event", {"event": "client.balance_low"},
        [_msg(["client"], ["email"], "Time to top up",
              "Hello {{ recipient.first_name }},\n\nYour prepaid balance is running low. Top "
              "up in the client portal to keep lessons going.")],
    ),
    Recipe(
        "invoice_overdue", "Overdue invoice: remind, task, then pause bookings",
        "Text the family and task the account manager when an invoice is overdue; if it's "
        "unpaid 16 days later, tag the client so bookings are paused.",
        "event", {"event": "invoice.overdue"},
        [
            _msg(["client"], ["sms", "email"], "Invoice {{ invoice.number }} is overdue",
                 "Invoice {{ invoice.number }} ({{ invoice.balance_due }} "
                 "{{ invoice.currency }}) is overdue. Please pay in the client portal."),
            _task("Call {{ invoice.client.name }} about invoice {{ invoice.number }}"),
            {"type": "wait", "days": 16},
            {"type": "branch",
             "if": {"field": "invoice.status", "op": "in", "value": ["issued", "partially_paid"]},
             "then": [{"type": "action", "action": "add_tag",
                       "config": {"tag": "Bookings paused"}}],
             "else": []},
        ],
    ),
    Recipe(
        "check_expiring", "Check expiring in 60 days: tell the tutor",
        "Email the tutor and create a task when a compliance check is 60 days from expiry.",
        "event", {"event": "compliance.expiring"},
        [
            _msg(["tutor"], ["email"], "{{ compliance_record.requirement }} expires soon",
                 "Hello {{ recipient.first_name }},\n\nYour "
                 "{{ compliance_record.requirement }} expires on "
                 "{{ compliance_record.expiry_date }}. Please upload the renewal."),
            _task("Renewal: {{ compliance_record.tutor.full_name }}'s "
                  "{{ compliance_record.requirement }}", "", 24 * 14),
        ],
        {"field": "event.data.days", "op": "equals", "value": 60},
    ),
    Recipe(
        "birthdays", "Birthday messages (opt-in)",
        "On a student's birthday, send the family a message. Only students tagged "
        "“Birthday messages” are included.",
        "date", {"subject": "student", "field": "date_of_birth", "offset_days": 0,
                 "anniversary": True, "time": "08:00"},
        [_msg(["client"], ["email"], "Happy birthday, {{ student.first_name }}!",
              "Hello {{ recipient.first_name }},\n\nEveryone here wishes "
              "{{ student.first_name }} a very happy birthday!")],
        {"field": "student.tags", "op": "contains", "value": "Birthday messages"},
    ),
    Recipe(
        "tutor_approved", "Tutor approved: onboarding tasks",
        "When a tutor application is approved, create the welcome tasks.",
        "event", {"event": "application.approved"},
        [
            _task("Welcome call with {{ tutor_application.full_name }}", "owner", 48),
            _task("Book {{ tutor_application.full_name }}'s induction", "owner", 24 * 7),
        ],
    ),
]  # fmt: skip


def recipe(key: str) -> Recipe | None:
    return next((r for r in RECIPES if r.key == key), None)


def install(key: str, *, user: Any = None) -> Any:
    from . import services

    found = recipe(key)
    if found is None:
        return None
    return services.create_automation(
        name=found.name,
        description=found.description,
        trigger_type=found.trigger_type,
        trigger_config=dict(found.trigger_config),
        conditions_=dict(found.conditions),
        steps=list(found.steps),
        recipe_key=found.key,
        user=user,
    )

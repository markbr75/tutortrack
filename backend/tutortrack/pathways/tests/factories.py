"""Helpers for pathway tests: a job, a tutor who can sign in, and templates."""

from __future__ import annotations

from typing import Any

from tutortrack.catalogue.tests.factories import ServiceFactory, SubjectFactory
from tutortrack.core.context import tenant_context
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.jobs import services as jobs
from tutortrack.pathways import services
from tutortrack.people.tests.factories import StudentFactory, TutorProfileFactory


def make_job(org: Any) -> Any:
    with tenant_context(org):
        subject = SubjectFactory(organisation=org)
        service = ServiceFactory(organisation=org, subject=subject)
        student = StudentFactory(organisation=org)
        return jobs.create_job(
            client=student.client, service=service, students=[{"student": student}],
            subject=subject, status="seeking_tutor",
        )  # fmt: skip


def make_tutor(org: Any) -> Any:
    """A tutor with an active login (the Tutor role)."""
    with tenant_context(org):
        membership = MembershipFactory(organisation=org, role="tutor")
        return TutorProfileFactory(organisation=org, membership=membership, status="active")


def sign(key: str = "agreement", **extra: Any) -> dict[str, Any]:
    return {
        "key": key, "type": "sign", "name": "Sign the job agreement",
        "config": {"title": "Job agreement", "text": "I'll arrive on time."}, **extra,
    }  # fmt: skip


def acknowledge(key: str = "safeguarding", **extra: Any) -> dict[str, Any]:
    return {
        "key": key, "type": "acknowledge", "name": "Read the safeguarding policy",
        "config": {"title": "Safeguarding", "text": "Tell the DSL about any concern."}, **extra,
    }  # fmt: skip


def review(key: str = "check", **extra: Any) -> dict[str, Any]:
    return {
        "key": key, "type": "staff_review", "assignee": "staff", "name": "Coordinator check",
        "config": {"question": "Is the tutor ready?"}, **extra,
    }  # fmt: skip


def questions(key: str = "about", **extra: Any) -> dict[str, Any]:
    return {
        "key": key, "type": "questions", "name": "About you",
        "config": {
            "fields": [
                {"key": "experience", "label": "Years teaching", "type": "number",
                 "required": True},
                {"key": "boards", "label": "Exam boards", "type": "multiselect",
                 "options": ["AQA", "Edexcel"]},
            ],
            **extra.pop("config", {}),
        },
        **extra,
    }  # fmt: skip


TWO_STAGES = [
    {"key": "paperwork", "name": "Paperwork", "steps": [sign(), acknowledge()]},
    {"key": "ready", "name": "Ready to teach", "gate": "ready", "steps": [review()]},
]


def make_template(org: Any, stages: Any = None, **fields: Any) -> Any:
    with tenant_context(org):
        return services.save_template(
            name=fields.pop("name", "Join a GCSE job"),
            subject_type=fields.pop("subject_type", "job"),
            stages=stages if stages is not None else TWO_STAGES,
            kind=fields.pop("kind", "join"),
            **fields,
        )

"""Online subject tests for tutors (FR-18-3, gap batch G5a), on the E21 quiz engine.

Staff build a quiz with the purpose "Tutor subject test" for a subject (and optionally a
level) in Learning > Quizzes. A tutor who teaches that subject sees it in the tutor portal
(Subject tests) and takes it; the quiz is auto-marked (``learning.services.take_quiz`` with
no student). Passing moves the matching subjects from ``claimed`` to ``assessed`` with the
score as evidence; approval stays a staff decision. A failed test can be retaken after
``recruitment.subject_test_retake_days``; a passed one is not taken again.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.people.models import TutorProfile, TutorSubject
from tutortrack.tenancy.settings_service import get_setting


def _matches(quiz: Any, subject: TutorSubject) -> bool:
    if quiz.subject_id is None:
        return False
    same_subject = subject.catalogue_subject_id == quiz.subject_id or (
        subject.subject.strip().lower() == quiz.subject.name.strip().lower()
    )
    if not same_subject:
        return False
    if quiz.level_id is None:
        return True
    return subject.catalogue_level_id == quiz.level_id or (
        subject.level.strip().lower() == quiz.level.name.strip().lower()
    )


def _user_id(tutor: TutorProfile) -> Any:
    membership = tutor.membership
    return membership.user_id if membership is not None else None


def tests_for(tutor: TutorProfile) -> list[dict[str, Any]]:
    """The tests for the subjects the tutor teaches, with their latest attempt."""
    from tutortrack.core.time import now
    from tutortrack.learning import selectors

    subjects = list(TutorSubject.objects.filter(tutor=tutor))
    user_id = _user_id(tutor)
    attempts: dict[str, Any] = {}
    if user_id is not None:
        for attempt in selectors.tutor_test_attempts([user_id]).order_by("-submitted_at"):
            attempts.setdefault(str(attempt.quiz_id), attempt)
    retake_days = int(get_setting("recruitment.subject_test_retake_days"))
    out = []
    for quiz in selectors.tutor_tests():
        matching = [s for s in subjects if _matches(quiz, s)]
        if not matching:
            continue
        last = attempts.get(str(quiz.pk))
        retake_at = None
        if last is not None and not last.passed:
            retake_at = last.submitted_at + timedelta(days=retake_days)
        status = "not_taken" if last is None else ("passed" if last.passed else "failed")
        out.append(
            {
                "quiz": quiz,
                "subjects": [f"{s.subject} {s.level}".strip() for s in matching],
                "status": status,
                "percent": last.percent if last else None,
                "taken_at": last.submitted_at if last else None,
                "retake_at": retake_at,
                "can_take": user_id is not None
                and bool(quiz.questions.all())
                and (last is None or (not last.passed and (retake_at or now()) <= now())),
            }
        )
    return out


def entry_for(tutor: TutorProfile, quiz_id: Any) -> dict[str, Any]:
    found = next((t for t in tests_for(tutor) if str(t["quiz"].pk) == str(quiz_id)), None)
    if found is None:
        raise NotFound()
    return found


@transaction.atomic
def take(
    tutor: TutorProfile, quiz_id: Any, *, answers: dict[str, Any], user: Any
) -> dict[str, Any]:
    from tutortrack.learning import services as learning

    from . import services

    entry = entry_for(tutor, quiz_id)
    if not entry["can_take"]:
        if entry["status"] == "passed":
            raise BusinessRuleViolation(_("You have already passed this test."))
        raise BusinessRuleViolation(
            _("You can take this test again from %(date)s.")
            % {"date": entry["retake_at"].date().isoformat() if entry["retake_at"] else ""},
            extra={"code": "retake_too_soon"},
        )
    quiz = entry["quiz"]
    attempt = learning.take_quiz(quiz, answers=answers, user=user)
    assessed: list[str] = []
    if attempt.passed:
        evidence = _('Online test "%(title)s": %(percent)s%% (pass mark %(pass)s%%)') % {
            "title": quiz.title,
            "percent": attempt.percent.quantize(Decimal("1")),
            "pass": quiz.pass_percent,
        }
        for subject in TutorSubject.objects.filter(tutor=tutor):
            if _matches(quiz, subject) and subject.competency == TutorSubject.Competency.CLAIMED:
                services.assess_subject(
                    subject, status=TutorSubject.Competency.ASSESSED, evidence=evidence, user=user
                )
                assessed.append(f"{subject.subject} {subject.level}".strip())
    return {
        "percent": attempt.percent,
        "passed": attempt.passed,
        "pass_percent": quiz.pass_percent,
        "assessed": assessed,
    }


def results_for(tutor: TutorProfile) -> list[Any]:
    """Every subject-test attempt by the tutor (for staff on the tutor record)."""
    from tutortrack.learning import selectors

    user_id = _user_id(tutor)
    if user_id is None:
        return []
    return list(selectors.tutor_test_attempts([user_id]).order_by("-submitted_at"))

"""E21-T07 lending library (FR-21-7) and E21-T08 built-in quizzes (FR-21-5, Phase 3b)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tutortrack.billing.models import Charge
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation, Conflict
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.learning import marking, services
from tutortrack.learning.models import Assessment, AssessmentResult, Loan, QuizAttempt

from .conftest import at, events_of, set_learning
from .factories import LibraryItemFactory

ITEMS = "/api/v1/learning/library-items"
LOANS = "/api/v1/learning/loans"


# --- lending library ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_lending_until_none_are_left(org, world):
    created = world["admin_api"].post(
        ITEMS,
        {
            "name": "Violin (3/4)",
            "kind": "instrument",
            "quantity": 1,
            "replacement_cost": {"amount": "120.00", "currency": "GBP"},
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    item = created.json()
    assert item["available"] == 1
    loan = world["admin_api"].post(
        LOANS, {"item": item["id"], "student": str(world["student"].pk)}, format="json"
    )
    assert loan.status_code == 201, loan.content
    with tenant_context(org):
        expected_due = services.org_today() + timedelta(days=28)
    assert loan.json()["due_date"] == expected_due.isoformat()
    assert events_of(org, "loan.created")[0]["data"]["due_date"] == expected_due.isoformat()
    none_left = world["admin_api"].post(
        LOANS, {"item": item["id"], "student": str(world["sibling"].pk)}, format="json"
    )
    assert none_left.status_code == 409
    back = world["admin_api"].post(
        f"{LOANS}/{loan.json()['id']}/return", {"notes": "Fine"}, format="json"
    )
    assert back.json()["status"] == "returned"
    assert events_of(org, "loan.returned")
    assert world["admin_api"].get(f"{ITEMS}/{item['id']}").json()["available"] == 1
    assert (
        world["tutor_api"]
        .post(LOANS, {"item": item["id"], "student": str(world["student"].pk)}, format="json")
        .status_code
        == 403
    )  # tutors don't run the library


@pytest.mark.django_db
def test_lost_items_are_charged_once(org, world):
    item = LibraryItemFactory(organisation=org, name="Revision guide")
    with tenant_context(org):
        loan = services.lend(item, world["student"])
    url = f"{LOANS}/{loan.pk}/lost"
    headers = {"HTTP_IDEMPOTENCY_KEY": "lost-1"}
    first = world["admin_api"].post(url, {"charge": True}, format="json", **headers)
    assert first.status_code == 200, first.content
    assert first.json()["status"] == "lost"
    replay = world["admin_api"].post(url, {"charge": True}, format="json", **headers)
    assert replay["Idempotent-Replayed"] == "true"
    again = world["admin_api"].post(url, {"charge": True}, format="json")
    assert again.status_code == 200
    with tenant_context(org):
        charges = Charge.objects.filter(client=world["family"]["client"])
        assert [c.gross for c in charges] == [Money("9.99", "GBP")]
        assert charges[0].description == "Replacement: Revision guide"
    lost = events_of(org, "loan.lost")
    assert len(lost) == 1
    assert lost[0]["data"]["charged"] == {"amount": "9.99", "currency": "GBP"}
    returned = world["admin_api"].post(f"{LOANS}/{loan.pk}/return")
    assert returned.status_code == 409


@pytest.mark.django_db
def test_charging_needs_the_charge_permission(org, world):
    item = LibraryItemFactory(organisation=org)
    with tenant_context(org):
        loan = services.lend(item, world["student"])
        with pytest.raises(BusinessRuleViolation):
            free = LibraryItemFactory(organisation=org, replacement_cost_amount=None)
            services.mark_lost(services.lend(free, world["sibling"]), charge=True)
    from tutortrack.core.testing import client_for
    from tutortrack.identity.tests.factories import MembershipFactory

    teacher = MembershipFactory(organisation=org, role="branch_manager")
    response = client_for(org, teacher.user).post(
        f"{LOANS}/{loan.pk}/lost", {"charge": False}, format="json"
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_overdue_steps_and_notices(org, world):
    set_learning(org, loan_overdue_notices=2)
    item = LibraryItemFactory(organisation=org)
    with tenant_context(org):
        loan = services.lend(
            item, world["student"], due_date=services.org_today() + timedelta(days=5)
        )
        state = services.loan_state(loan.pk)
        assert state["remind"]
        assert state["open"]
        assert not state["overdue"]
        assert services.send_loan_reminder(loan.pk) is True
        assert services.send_loan_reminder(loan.pk) is False
        Loan.objects.filter(pk=loan.pk).update(
            lent_on=services.org_today() - timedelta(days=10),
            due_date=services.org_today() - timedelta(days=1),
        )
        assert services.mark_loan_overdue(loan.pk) is True
        assert services.mark_loan_overdue(loan.pk) is False
        assert services.send_overdue_notice(loan.pk) is True
        assert services.send_overdue_notice(loan.pk) is True
        assert services.send_overdue_notice(loan.pk) is False  # notices run out
        assert services.loan_state(loan.pk)["notices"] == 2
    assert len(events_of(org, "loan.overdue")) == 1
    listed = world["admin_api"].get(LOANS, {"overdue": "true"}).json()["results"]
    assert [x["id"] for x in listed] == [str(loan.pk)]
    portal = world["family"]["api"].get("/api/v1/portal/learning/loans").json()
    assert portal[0]["is_overdue"] is True
    assert world["others"]["api"].get("/api/v1/portal/learning/loans").json() == []
    extended = world["admin_api"].post(
        f"{LOANS}/{loan.pk}/extend",
        {"due_date": (now().date() + timedelta(days=14)).isoformat()},
        format="json",
    )
    assert extended.json()["overdue_at"] is None


# --- quizzes ------------------------------------------------------------------------------------

QUIZ = {
    "title": "Fractions check",
    "pass_percent": 60,
    "questions": [
        {
            "kind": "single",
            "prompt": "Which equals 1/2?",
            "choices": [{"text": "2/4"}, {"text": "2/3"}],
            "answer": ["a"],
        },
        {
            "kind": "multiple",
            "prompt": "Which are bigger than 1/2?",
            "choices": [{"text": "3/4"}, {"text": "1/3"}, {"text": "5/6"}],
            "answer": ["a", "c"],
        },
        {"kind": "short", "prompt": "Simplify 4/8", "answer": ["1/2", "a half"], "points": 2},
    ],
}


def quiz_homework(org, world):
    created = world["tutor_api"].post("/api/v1/learning/quizzes", QUIZ, format="json")
    assert created.status_code == 201, created.content
    homework = world["tutor_api"].post(
        "/api/v1/learning/homework",
        {
            "title": "Quiz: fractions",
            "due_at": at(3, 18).isoformat(),
            "students": [str(world["student"].pk)],
            "quiz": created.json()["id"],
        },
        format="json",
    )
    assert homework.status_code == 201, homework.content
    assert homework.json()["submission_type"] == "quiz"
    return created.json(), homework.json()


@pytest.mark.django_db
def test_questions_are_validated(org, world):
    bad_single = {**QUIZ, "questions": [{**QUIZ["questions"][0], "answer": ["a", "b"]}]}
    assert (
        world["admin_api"].post("/api/v1/learning/quizzes", bad_single, format="json").status_code
        == 422
    )
    one_choice = {**QUIZ, "questions": [{**QUIZ["questions"][0], "choices": [{"text": "x"}]}]}
    assert (
        world["admin_api"].post("/api/v1/learning/quizzes", one_choice, format="json").status_code
        == 422
    )
    no_answer = {**QUIZ, "questions": [{"kind": "short", "prompt": "?", "answer": []}]}
    assert (
        world["admin_api"].post("/api/v1/learning/quizzes", no_answer, format="json").status_code
        == 422
    )


@pytest.mark.django_db
def test_quiz_homework_is_marked_automatically(org, world):
    quiz, _homework = quiz_homework(org, world)
    family = world["family"]["api"]
    [card] = family.get("/api/v1/portal/learning/homework").json()
    questions = card["quiz"]["questions"]
    assert "answer" not in questions[0]  # never sent to the learner
    answers = {
        questions[0]["id"]: "a",
        questions[1]["id"]: ["c"],  # half right is wrong
        questions[2]["id"]: "  A Half. ",
    }
    done = family.post(
        f"/api/v1/portal/learning/homework/{card['id']}/submit",
        {"quiz_answers": answers},
        format="json",
    )
    assert done.status_code == 201, done.content
    body = done.json()
    assert (body["status"], body["grade"]) == ("completed", "75%")
    assert body["quiz"] is None
    assert body["quiz_result"]["passed"] is True
    with tenant_context(org):
        attempt = QuizAttempt.objects.get()
        assert (attempt.score, attempt.max_score, attempt.percent) == (
            Decimal(3),
            Decimal(4),
            Decimal("75.00"),
        )
        result = AssessmentResult.objects.get(student=world["student"])
        assert result.assessment.kind == Assessment.Kind.QUIZ
        assert result.percent == Decimal("75.00")
    assert events_of(org, "quiz.submitted")[0]["data"]["passed"] is True
    assert events_of(org, "homework.graded")[0]["data"]["grade"] == "75%"
    locked = world["tutor_api"].patch(
        f"/api/v1/learning/quizzes/{quiz['id']}",
        {"questions": QUIZ["questions"][:1]},
        format="json",
    )
    assert locked.status_code == 409
    attempts = world["tutor_api"].get("/api/v1/learning/quiz-attempts").json()["results"]
    assert attempts[0]["percent"] == "75.00"


@pytest.mark.django_db
def test_tutors_keep_their_quizzes(org, world):
    quiz, _homework = quiz_homework(org, world)
    edit = world["other_api"].patch(
        f"/api/v1/learning/quizzes/{quiz['id']}", {"title": "x"}, format="json"
    )
    assert edit.status_code == 404
    with tenant_context(org):
        from tutortrack.learning.models import Quiz

        with pytest.raises(Conflict):
            services.take_quiz(Quiz.objects.create(title="Empty"), answers={})


def test_short_answers_ignore_case_spaces_and_end_punctuation():
    assert marking.mark_question("short", ["Paris"], 1, "  paris. ") == (True, 1)
    assert marking.mark_question("short", ["café"], 1, "Cafe") == (True, 1)
    assert marking.mark_question("short", ["Paris"], 1, "Lyon") == (False, 0)
    assert marking.mark_question("multiple", ["a", "c"], 2, ["c", "a"]) == (True, 2)
    assert marking.mark_question("multiple", ["a", "c"], 2, ["a"]) == (False, 0)
    assert marking.mark_question("single", ["b"], 1, "b") == (True, 1)
    assert marking.mark_question("single", ["b"], 1, None) == (False, 0)


@given(
    st.lists(
        st.tuples(st.integers(min_value=1, max_value=10), st.booleans()), min_size=1, max_size=30
    )
)
def test_quiz_score_is_the_sum_of_correct_points(rows):
    questions = [
        {"id": str(i), "kind": "single", "answer": ["a"], "points": points}
        for i, (points, _right) in enumerate(rows)
    ]
    answers = {str(i): "a" if right else "b" for i, (_points, right) in enumerate(rows)}
    marked = marking.mark_quiz(questions, answers)
    assert marked["score"] == sum(p for p, right in rows if right)
    assert marked["max_score"] == sum(p for p, _ in rows)
    assert Decimal(0) <= marked["percent"] <= Decimal(100)
    assert (marked["percent"] == 100) == all(right for _p, right in rows)

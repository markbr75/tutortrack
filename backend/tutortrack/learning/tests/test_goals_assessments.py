"""E21-T04 goals and milestones (FR-21-4) and E21-T05 assessments, results and score
trends (FR-21-5)."""

from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tutortrack.core.context import tenant_context
from tutortrack.learning import marking, services
from tutortrack.learning.models import AssessmentResult, Goal, GradeScale

from .conftest import events_of, set_learning

URL = "/api/v1/learning/goals"


def goal_payload(world, **extra):
    return {
        "student": str(world["student"].pk),
        "kind": "target_grade",
        "title": "Grade 7 in GCSE Maths",
        "target_grade": "7",
        "milestones": [{"title": "Grade 6 in the mock"}, {"title": "Algebra secure"}],
        **extra,
    }


@pytest.mark.django_db
def test_goals_with_milestones_are_achieved_when_all_are_done(org, world):
    created = world["tutor_api"].post(URL, goal_payload(world), format="json")
    assert created.status_code == 201, created.content
    goal = created.json()
    assert goal["progress_percent"] == 0
    assert events_of(org, "goal.created")[0]["data"]["title"] == "Grade 7 in GCSE Maths"
    first, second = (m["id"] for m in goal["milestones"])
    half = world["tutor_api"].post(
        f"{URL}/{goal['id']}/milestone", {"milestone": first, "done": True}, format="json"
    )
    assert half.json()["progress_percent"] == 50
    assert half.json()["status"] == "active"
    done = world["tutor_api"].post(
        f"{URL}/{goal['id']}/milestone", {"milestone": second, "done": True}, format="json"
    )
    assert (done.json()["status"], done.json()["progress_percent"]) == ("achieved", 100)
    assert len(events_of(org, "goal.achieved")) == 1


@pytest.mark.django_db
def test_manual_progress_and_status(org, world):
    set_learning(org, goals_auto_achieve=False)
    created = (
        world["admin_api"]
        .post(
            URL,
            goal_payload(world, milestones=[], kind="custom", progress_percent=30),
            format="json",
        )
        .json()
    )
    assert created["progress_percent"] == 30
    too_much = world["admin_api"].patch(
        f"{URL}/{created['id']}", {"progress_percent": 120}, format="json"
    )
    assert too_much.status_code == 400
    stopped = world["admin_api"].post(
        f"{URL}/{created['id']}/status", {"status": "abandoned"}, format="json"
    )
    assert stopped.json()["status"] == "abandoned"
    achieved = world["admin_api"].post(
        f"{URL}/{created['id']}/status", {"status": "achieved"}, format="json"
    )
    assert achieved.json()["status"] == "achieved"
    assert events_of(org, "goal.achieved")


@pytest.mark.django_db
def test_family_sees_visible_goals_and_tutors_only_their_students(org, world):
    world["admin_api"].post(URL, goal_payload(world), format="json")
    world["admin_api"].post(
        URL, goal_payload(world, title="Private", visible_to_family=False), format="json"
    )
    portal = world["family"]["api"].get("/api/v1/portal/learning/goals").json()
    assert [g["title"] for g in portal] == ["Grade 7 in GCSE Maths"]
    assert world["others"]["api"].get("/api/v1/portal/learning/goals").json() == []
    denied = world["tutor_api"].post(
        URL, goal_payload(world, student=str(world["stranger"].pk)), format="json"
    )
    assert denied.status_code == 403
    assert world["other_api"].get(URL).json()["results"] == []


# --- assessments --------------------------------------------------------------------------------


@pytest.mark.django_db
def test_results_work_out_the_percentage(org, world):
    api = world["admin_api"]
    mock = api.post(
        "/api/v1/learning/assessments",
        {"name": "Autumn mock", "kind": "mock_exam", "held_on": "2026-10-01", "max_score": "80"},
        format="json",
    ).json()
    result = api.post(
        "/api/v1/learning/assessment-results",
        {
            "assessment": mock["id"],
            "student": str(world["student"].pk),
            "score": "54",
            "grade": "6",
        },
        format="json",
    )
    assert result.status_code == 201, result.content
    assert (result.json()["percent"], result.json()["taken_on"]) == ("67.50", "2026-10-01")
    recorded = events_of(org, "assessment.recorded")
    assert recorded[0]["data"]["percent"] == "67.50"
    corrected = api.patch(
        f"/api/v1/learning/assessment-results/{result.json()['id']}", {"score": "55"}, format="json"
    )
    assert corrected.json()["percent"] == "68.75"
    assert len(events_of(org, "assessment.recorded")) == 1  # corrections don't re-announce
    over = api.post(
        "/api/v1/learning/assessment-results",
        {"assessment": mock["id"], "student": str(world["sibling"].pk), "score": "81"},
        format="json",
    )
    assert over.status_code == 422


@pytest.mark.django_db
def test_grades_follow_the_assessment_scale(org, world):
    with tenant_context(org):
        services.ensure_default_scales()
        nine = GradeScale.objects.get(kind="numeric")
        assessment = services.save_assessment(
            None, name="Mock", kind="mock_exam", held_on=services.org_today(), grade_scale=nine
        )
        services.record_result(assessment=assessment, student=world["student"], grade="7")
        with pytest.raises(Exception, match="Choose a grade"):
            services.record_result(assessment=assessment, student=world["sibling"], grade="A")


@pytest.mark.django_db
def test_trend_is_oldest_first_and_filters_by_subject(org, world):
    with tenant_context(org):
        today = services.org_today()
        rows = [
            ("Diagnostic", 20, None, -60),
            ("Mock 1", 50, world["subject"], -30),
            ("Mock 2", 70, world["subject"], -2),
        ]
        for name, score, subject, days in rows:
            a = services.save_assessment(
                None,
                name=name,
                kind="mock_exam",
                held_on=today + timedelta(days=days),
                max_score=Decimal(100),
                subject=subject,
            )
            services.record_result(assessment=a, student=world["student"], score=Decimal(score))
    url = f"/api/v1/learning/students/{world['student'].pk}/trend"
    points = world["tutor_api"].get(url).json()
    assert [p["name"] for p in points] == ["Diagnostic", "Mock 1", "Mock 2"]
    assert [p["percent"] for p in points] == ["20.00", "50.00", "70.00"]
    maths = world["tutor_api"].get(url, {"subject": str(world["subject"].pk)}).json()
    assert [p["name"] for p in maths] == ["Mock 1", "Mock 2"]
    assert world["other_api"].get(url).status_code == 404
    portal = world["family"]["api"].get("/api/v1/portal/learning/results").json()
    assert [r["name"] for r in portal] == ["Diagnostic", "Mock 1", "Mock 2"]


@pytest.mark.django_db
def test_results_hidden_from_the_family_stay_hidden(org, world):
    with tenant_context(org):
        a = services.save_assessment(
            None, name="Internal", kind="diagnostic", held_on=services.org_today()
        )
        services.record_result(
            assessment=a, student=world["student"], grade="", visible_to_family=False
        )
        assert AssessmentResult.objects.count() == 1
    assert world["family"]["api"].get("/api/v1/portal/learning/results").json() == []


@given(
    score=st.decimals(min_value=0, max_value=1000, places=2),
    extra=st.decimals(min_value=0, max_value=1000, places=2),
)
def test_percent_rounds_half_up_to_two_places(score, extra):
    maximum = score + extra
    if maximum <= 0:
        return
    pct = marking.percent(score, maximum)
    exact = Fraction(score) * 100 / Fraction(maximum)
    expected = Decimal(exact.numerator) / Decimal(exact.denominator)
    assert pct == expected.quantize(Decimal("0.01"), ROUND_HALF_UP)
    assert Decimal(0) <= pct <= Decimal(100)
    assert pct.as_tuple().exponent == -2


@pytest.mark.parametrize(
    ("score", "maximum", "expected"),
    [("1", "8", "12.50"), ("1", "3", "33.33"), ("2", "3", "66.67"), ("1", "800", "0.13")],
)
def test_percent_examples(score, maximum, expected):
    assert str(marking.percent(Decimal(score), Decimal(maximum))) == expected


def test_goal_model_bounds():
    assert Goal.Status.ACHIEVED == "achieved"

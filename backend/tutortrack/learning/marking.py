"""Pure scoring rules (no database): percentages, grade scales and quiz auto-marking."""

from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation

HUNDRED = Decimal(100)
TWO_PLACES = Decimal("0.01")

DEFAULT_SCALES: tuple[tuple[str, str, list[str]], ...] = (
    ("Percentage", "percent", []),
    ("Letter grades (A*\N{EN DASH}U)", "letter", ["A*", "A", "B", "C", "D", "E", "U"]),
    ("GCSE 9\N{EN DASH}1", "numeric", ["9", "8", "7", "6", "5", "4", "3", "2", "1", "U"]),
    ("Effort (custom)", "custom", ["Excellent", "Good", "Satisfactory", "Needs work"]),
)


def percent(score: Decimal, max_score: Decimal) -> Decimal:
    """``score / max_score`` as a percentage, rounded half-up to 2 places."""
    if max_score <= 0:
        raise ValueError("max_score must be positive")
    return (Decimal(score) * HUNDRED / Decimal(max_score)).quantize(TWO_PLACES, ROUND_HALF_UP)


def check_grade(kind: str, grades: list[str], grade: str) -> str:
    """A grade valid on the scale (percent scales take ``0``-``100``)."""
    grade = (grade or "").strip()
    if not grade:
        return ""
    if kind == "percent":
        try:
            value = Decimal(grade.rstrip("%"))
        except ArithmeticError:
            value = Decimal(-1)
        if not Decimal(0) <= value <= HUNDRED:
            raise _invalid("grade", _("Give a percentage from 0 to 100."))
        return f"{value.normalize():f}%"
    if grade not in grades:
        raise _invalid("grade", _("Choose a grade from the scale."))
    return grade


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


# --- quizzes ------------------------------------------------------------------------------------


def normalise(text: Any) -> str:
    """Case, accents, punctuation at the ends and repeated spaces don't matter."""
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"\s+", " ", value).strip().strip(".!?,;:").strip()
    return value.casefold()


def clean_question(kind: str, choices: Any, answer: Any) -> tuple[list[dict[str, str]], list[str]]:
    """Validate a question's choices and correct answer."""
    if kind == "short":
        accepted = [str(a).strip()[:200] for a in (answer or []) if str(a).strip()]
        if not accepted:
            raise _invalid("answer", _("Give at least one accepted answer."))
        return [], accepted
    if not isinstance(choices, list) or not 2 <= len(choices) <= 10:
        raise _invalid("choices", _("Give between 2 and 10 choices."))
    cleaned = []
    for i, choice in enumerate(choices):
        text = str(choice.get("text", "") if isinstance(choice, dict) else choice).strip()
        if not text:
            raise _invalid("choices", _("Every choice needs some text."))
        choice_id = str(choice.get("id") or "") if isinstance(choice, dict) else ""
        cleaned.append({"id": choice_id or chr(ord("a") + i), "text": text[:500]})
    ids = [c["id"] for c in cleaned]
    if len(set(ids)) != len(ids):
        raise _invalid("choices", _("Choices need different ids."))
    correct = [str(a) for a in (answer or [])]
    if not correct or any(a not in ids for a in correct):
        raise _invalid("answer", _("Mark the correct choice."))
    if kind == "single" and len(correct) != 1:
        raise _invalid("answer", _("A one-answer question has exactly one correct choice."))
    return cleaned, sorted(set(correct))


def mark_question(kind: str, answer: list[str], points: int, given: Any) -> tuple[bool, int]:
    """(correct, points awarded). Multiple choice must match exactly; short answers match
    any accepted answer after ``normalise``."""
    if kind == "short":
        correct = normalise(given) in {normalise(a) for a in answer} if given else False
    else:
        chosen = given if isinstance(given, list) else [given] if given else []
        correct = sorted({str(c) for c in chosen}) == sorted(set(answer))
    return correct, points if correct else 0


def mark_quiz(questions: list[dict[str, Any]], answers: dict[str, Any]) -> dict[str, Any]:
    """``questions``: ``[{"id", "kind", "answer", "points"}]``. Returns score, max_score,
    percent (half-up, 2 places) and per-question marks."""
    score = 0
    total = 0
    marks: dict[str, dict[str, Any]] = {}
    for q in questions:
        qid = str(q["id"])
        correct, awarded = mark_question(q["kind"], q["answer"], int(q["points"]), answers.get(qid))
        marks[qid] = {"correct": correct, "points": awarded}
        score += awarded
        total += int(q["points"])
    pct = percent(Decimal(score), Decimal(total)) if total else Decimal("0.00")
    return {
        "score": Decimal(score),
        "max_score": Decimal(total),
        "percent": pct,
        "marks": marks,
    }

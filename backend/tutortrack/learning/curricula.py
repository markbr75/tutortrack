"""Built-in curriculum specifications and the CSV import format (FR-21-3).

Built-ins are outlines of common specifications (units and topics, with codes) that an
organisation installs as its own editable copy. CSV import takes one row per topic:

    unit,topic,code
    Number,Fractions,N1
    Number,Percentages,N2

``code`` is optional; a row with an empty ``topic`` adds the unit alone.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation

MAX_ROWS = 2000


@dataclass(frozen=True)
class BuiltinCurriculum:
    key: str
    name: str
    subject: str
    level: str
    exam_board: str
    units: tuple[tuple[str, tuple[str, ...]], ...]


def _units(*units: tuple[str, tuple[str, ...]]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return units


BUILTINS: dict[str, BuiltinCurriculum] = {
    c.key: c
    for c in (
        BuiltinCurriculum(
            key="gcse-maths",
            name="GCSE Mathematics",
            subject="Maths",
            level="GCSE",
            exam_board="",
            units=_units(
                (
                    "Number",
                    (
                        "Place value and ordering",
                        "Factors, multiples and primes",
                        "Fractions",
                        "Decimals",
                        "Percentages",
                        "Indices and roots",
                        "Standard form",
                        "Surds",
                        "Bounds and estimation",
                    ),
                ),
                (
                    "Algebra",
                    (
                        "Expressions and substitution",
                        "Expanding and factorising",
                        "Linear equations",
                        "Inequalities",
                        "Simultaneous equations",
                        "Quadratic equations",
                        "Sequences",
                        "Straight-line graphs",
                        "Quadratic and other graphs",
                        "Functions",
                        "Algebraic proof",
                    ),
                ),
                (
                    "Ratio, proportion and rates of change",
                    (
                        "Ratio",
                        "Direct and inverse proportion",
                        "Compound measures",
                        "Growth and decay",
                    ),
                ),
                (
                    "Geometry and measures",
                    (
                        "Angles and polygons",
                        "Area and perimeter",
                        "Volume and surface area",
                        "Pythagoras' theorem",
                        "Trigonometry",
                        "Transformations",
                        "Congruence and similarity",
                        "Circle theorems",
                        "Vectors",
                        "Constructions and loci",
                    ),
                ),
                (
                    "Probability",
                    (
                        "Basic probability",
                        "Tree diagrams",
                        "Venn diagrams",
                        "Conditional probability",
                    ),
                ),
                (
                    "Statistics",
                    (
                        "Averages and spread",
                        "Charts and graphs",
                        "Scatter graphs and correlation",
                        "Cumulative frequency and box plots",
                        "Histograms",
                        "Sampling",
                    ),
                ),
            ),
        ),
        BuiltinCurriculum(
            key="ks2-english",
            name="Key Stage 2 English",
            subject="English",
            level="KS2",
            exam_board="",
            units=_units(
                (
                    "Reading",
                    (
                        "Word reading and phonics",
                        "Retrieval",
                        "Inference",
                        "Vocabulary in context",
                        "Summarising",
                        "Prediction",
                        "Author's language and structure",
                        "Comparing texts",
                    ),
                ),
                (
                    "Writing: composition",
                    (
                        "Planning and drafting",
                        "Narrative writing",
                        "Non-fiction writing",
                        "Editing and improving",
                    ),
                ),
                ("Spelling", ("Prefixes and suffixes", "Homophones", "Statutory word lists")),
                (
                    "Grammar and punctuation",
                    (
                        "Word classes",
                        "Sentence types",
                        "Clauses and phrases",
                        "Tenses",
                        "Commas and apostrophes",
                        "Inverted commas",
                        "Colons, semi-colons and dashes",
                        "Active and passive voice",
                    ),
                ),
                ("Handwriting", ("Joined handwriting", "Presentation")),
            ),
        ),
        BuiltinCurriculum(
            key="sat-math",
            name="SAT Math",
            subject="Maths",
            level="SAT",
            exam_board="College Board",
            units=_units(
                (
                    "Algebra",
                    (
                        "Linear equations in one variable",
                        "Linear functions",
                        "Linear equations in two variables",
                        "Systems of linear equations",
                        "Linear inequalities",
                    ),
                ),
                (
                    "Advanced math",
                    ("Equivalent expressions", "Nonlinear equations", "Nonlinear functions"),
                ),
                (
                    "Problem-solving and data analysis",
                    (
                        "Ratios, rates and proportions",
                        "Percentages",
                        "One-variable data",
                        "Two-variable data",
                        "Probability",
                        "Inference and margin of error",
                        "Evaluating statistical claims",
                    ),
                ),
                (
                    "Geometry and trigonometry",
                    (
                        "Area and volume",
                        "Lines, angles and triangles",
                        "Right triangles and trigonometry",
                        "Circles",
                    ),
                ),
            ),
        ),
    )
}


def builtin_codes(curriculum: BuiltinCurriculum) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """Units with codes (``U1``) and their topics (``U1.1``...)."""
    out = []
    for u, (unit, topics) in enumerate(curriculum.units, start=1):
        out.append((f"U{u}", unit, [(f"U{u}.{t}", name) for t, name in enumerate(topics, 1)]))
    return out


@dataclass
class ParsedUnit:
    name: str
    code: str = ""
    topics: list[tuple[str, str]] = field(default_factory=list)  # (name, code)


def _bad(message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {"file": [message]}})


def parse_csv(text: str) -> list[ParsedUnit]:
    """Units in file order with their topics. Raises with the first problem row."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = [h.strip().lower() for h in reader.fieldnames or []]
    if "unit" not in headers or "topic" not in headers:
        raise _bad(_("The file needs 'unit' and 'topic' columns."))
    units: dict[str, ParsedUnit] = {}
    codes: set[str] = set()
    for number, raw in enumerate(reader, start=2):
        if number > MAX_ROWS + 1:
            raise _bad(_("A curriculum file can have at most %(n)s rows.") % {"n": MAX_ROWS})
        row = {str(k).strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        unit, topic, code = row.get("unit", ""), row.get("topic", ""), row.get("code", "")
        if not unit:
            raise _bad(_("Row %(row)s has no unit.") % {"row": number})
        if len(unit) > 200 or len(topic) > 200 or len(code) > 40:
            raise _bad(_("Row %(row)s has a value that is too long.") % {"row": number})
        if code:
            if code in codes:
                raise _bad(
                    _("Row %(row)s repeats the code %(code)s.") % {"row": number, "code": code}
                )
            codes.add(code)
        parsed = units.setdefault(unit.casefold(), ParsedUnit(unit))
        if topic:
            parsed.topics.append((topic, code))
        elif code and not parsed.code:
            parsed.code = code
    if not units:
        raise _bad(_("The file has no rows."))
    return list(units.values())

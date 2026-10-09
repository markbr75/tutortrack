"""Starter subjects and levels per country (FR-06-1), copied into each new organisation.

Organisations edit, reorder and archive them freely; nothing refers back to this file.
"""

from __future__ import annotations

CATEGORIES = ["Academic", "Languages", "Music", "Test Prep", "Coding"]

_UK_SCHOOL = ["KS1", "KS2", "KS3", "GCSE Foundation", "GCSE Higher", "A Level"]
_UK_BOARDS = ["AQA", "Edexcel", "OCR", "WJEC"]
_US_SCHOOL = ["Elementary", "Middle School", "High School", "AP", "College"]
_AU_SCHOOL = ["Primary", "Years 7-10", "Year 11-12"]
_IE_SCHOOL = ["Primary", "Junior Cycle", "Leaving Cert Ordinary", "Leaving Cert Higher"]
_NZ_SCHOOL = ["Primary", "Years 7-10", "NCEA Level 1", "NCEA Level 2", "NCEA Level 3"]
_CA_SCHOOL = ["Elementary", "Grades 7-8", "Grades 9-10", "Grades 11-12", "University"]
_INSTRUMENT = ["Beginner", "Grade 1-3", "Grade 4-5", "Grade 6-8", "Diploma"]

# country -> [(subject, category, levels, exam boards)]
SubjectSeed = tuple[str, str, list[str], list[str]]


def _academic(levels: list[str], boards: list[str], extra: list[SubjectSeed]) -> list[SubjectSeed]:
    core = ["Maths", "English", "Biology", "Chemistry", "Physics", "History", "Geography"]
    return [
        *[(name, "Academic", levels, boards) for name in core],
        ("French", "Languages", levels, boards),
        ("Spanish", "Languages", levels, boards),
        ("Piano", "Music", _INSTRUMENT, []),
        ("Guitar", "Music", _INSTRUMENT, []),
        ("Coding", "Coding", ["Beginner", "Intermediate", "Advanced"], []),
        *extra,
    ]


SUBJECTS: dict[str, list[SubjectSeed]] = {
    "GB": _academic(
        _UK_SCHOOL,
        _UK_BOARDS,
        [
            (
                "11+",
                "Test Prep",
                ["Verbal reasoning", "Non-verbal reasoning", "Maths", "English"],
                ["GL", "CEM"],
            ),
            ("Computer Science", "Academic", ["GCSE", "A Level"], _UK_BOARDS),
        ],
    ),
    "US": _academic(
        _US_SCHOOL,
        ["College Board"],
        [
            ("SAT", "Test Prep", ["Math", "Reading and Writing"], ["College Board"]),
            ("ACT", "Test Prep", ["Math", "English", "Science", "Reading"], []),
        ],
    ),
    "AU": _academic(_AU_SCHOOL, [], [("Selective Schools", "Test Prep", ["Year 6"], [])]),
    "CA": _academic(_CA_SCHOOL, [], []),
    "IE": _academic(_IE_SCHOOL, ["SEC"], []),
    "NZ": _academic(_NZ_SCHOOL, ["NZQA"], []),
}

# country -> [(name, percent, is_default, exempt_reason)]
TAX_RATES: dict[str, list[tuple[str, str, bool, str]]] = {
    "GB": [
        ("Exempt (education)", "0", True, "VAT exempt private tuition"),
        ("Standard VAT", "20", False, ""),
        ("Zero rated", "0", False, ""),
    ],
    "IE": [
        ("Exempt (education)", "0", True, "VAT exempt education"),
        ("Standard VAT", "23", False, ""),
    ],
    "AU": [
        ("GST free (education)", "0", True, "GST-free education course"),
        ("GST", "10", False, ""),
    ],
    "NZ": [("GST", "15", True, "")],
    "CA": [("No tax", "0", True, "")],
    "US": [("No sales tax", "0", True, "")],
}


def subjects_for(country: str) -> list[SubjectSeed]:
    return SUBJECTS.get(
        country.upper(), SUBJECTS["GB"] if country.upper() == "UK" else SUBJECTS["US"]
    )


def tax_rates_for(country: str) -> list[tuple[str, str, bool, str]]:
    return TAX_RATES.get(country.upper(), [("No tax", "0", True, "")])

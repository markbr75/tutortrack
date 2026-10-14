"""Golden eval cases, at least one per prompt. Inputs are what the features send (already
pseudonymised); checks are properties a good answer must have, loose enough for a real
model's wording and strict on facts, placeholders, schema and tool use."""

from __future__ import annotations

import json

from ..features.lesson_report import output_schema
from . import Case

STYLE = "Style: friendly tone, UK English spelling.\n\n"
TODAY = "Today is Wednesday 14 October 2026, 09:30 in Europe/London.\n\n"

REPORT_FIELDS = [
    {"key": "covered", "label": "What we covered", "type": "rich_text", "visibility": "student"},
    {"key": "effort", "label": "Effort", "type": "rating", "visibility": "client"},
    {"key": "homework", "label": "Homework", "type": "homework", "visibility": "student"},
    {
        "key": "parent_notes",
        "label": "Notes for parent",
        "type": "rich_text",
        "visibility": "client",
    },
]
TOPICS = ["0192-fractions", "0192-algebra"]

CASES: list[Case] = [
    Case(
        name="lesson report from rough notes",
        prompt="lesson_report.draft",
        schema=output_schema(REPORT_FIELDS, TOPICS),
        content=STYLE
        + "Lesson: Maths with [STUDENT_1]\nSubject: Maths GCSE\nDate: Tuesday 13 October 2026, "
        "60 minutes\nStudents: [STUDENT_1]\n\nReport template fields (key, type, audience, "
        "options):\n- covered: What we covered (rich_text, audience student)\n- effort: Effort "
        "(rating, audience client)\n- homework: Homework (homework, audience student)\n- "
        "parent_notes: Notes for parent (rich_text, audience client)\n\nCandidate curriculum "
        "topics (id: unit > topic):\n- 0192-fractions: Number > Fractions\n- 0192-algebra: "
        'Algebra > Expanding brackets\n\nTutor\'s notes:\n"""\n[STUDENT_1_FIRST] adding '
        "fractions with different denominators, got it by the end, still mixes up mixed "
        'numbers. Worked hard. hw worksheet 4\n"""',
        expect={
            "json_keys": ["answers", "suggested_topic_ids", "homework"],
            "contains": ["[STUDENT_1_FIRST]", "fraction"],
            "non_empty": ["answers.covered"],
            "not_contains": ["algebra"],
        },
    ),
    Case(
        name="progress comments stay with the facts",
        prompt="progress.summary",
        content=STYLE
        + "Student: [STUDENT_1]\nReport: Autumn term (2026-09-01 to 2026-10-14)\n\nFacts "
        "(JSON):\n"
        + json.dumps(
            {
                "attendance": {"lessons": 4, "attended": 3, "rate": "75.0"},
                "goals": [{"title": "Grade 7", "status": "active", "progress_percent": 50}],
                "topics": {"covered": [{"name": "Fractions", "level": "secure", "lessons": 2}]},
            },
            sort_keys=True,
        ),
        expect={
            "contains": ["[STUDENT_1"],
            "contains_any": ["3 of 4", "three of four", "3 out of 4", "75"],
            "not_contains": ["grade 9", "[STUDENT_2"],
        },
    ),
    Case(
        name="explain to a parent",
        prompt="parent.rewrite",
        content=STYLE
        + 'Target language: the same language as the text\n\nText:\n"""\n[STUDENT_1_FIRST] '
        'is secure at KS3 fractions and is working towards AO2 problem solving.\n"""',
        expect={"json_keys": ["text", "language"], "contains": ["[STUDENT_1_FIRST]"]},
    ),
    Case(
        name="explain to a parent in French",
        prompt="parent.rewrite",
        content=STYLE
        + 'Target language: French\n\nText:\n"""\n[STUDENT_1_FIRST] did well in the KS3 '
        'fractions test.\n"""',
        expect={"json_keys": ["text"], "contains": ["[STUDENT_1_FIRST]"], "non_empty": ["text"]},
    ),
    Case(
        name="enquiry extraction",
        prompt="enquiry.extract",
        content=STYLE
        + 'Enquiry text:\n"""\nHi, I\'m Priya, my son Kabir needs GCSE maths help before his '
        "mocks. Tuesdays after 4pm are best, online please. We're in LS6 2AB. Call [PHONE_1] or "
        '[EMAIL_1].\n"""',
        expect={
            "equals": {
                "location.postcode": "LS6 2AB",
                "location.mode": "online",
                "contact.email": "[EMAIL_1]",
            },
            "list_contains": {"subjects.subject": "Maths", "students.first_name": "Kabir"},
            "non_empty": ["availability"],
        },
    ),
    Case(
        name="enquiry triage",
        prompt="enquiry.triage",
        content=STYLE
        + "Enquiry: GCSE maths for [STUDENT_1_FIRST]\nSource: email; status: open; stage: New\n"
        'Subjects on record: []\n\nEnquiry notes:\n"""\n[CONTACT_1] wants GCSE maths for her '
        'son before mocks in November, online, Tuesdays.\n"""\n\nExtracted details (JSON):\n'
        '{"availability": ["Tuesdays"], "subjects": [{"level": "GCSE", "subject": "Maths"}], '
        '"urgency": "high"}',
        expect={
            "json_keys": ["next_steps", "priority", "reply_subject", "reply_body"],
            "one_of": {"priority": ["high", "normal"]},
            "contains": ["[CONTACT_1"],
            "not_contains": ["£", "$"],
        },
    ),
    Case(
        name="suggested reply",
        prompt="inbox.reply",
        content=STYLE
        + "Conversation: Lessons (channel email)\n\nAccount context:\nUpcoming lesson: Maths, Thu "
        "15 Oct 16:00\nCancellation policy: free with at least 24 hours' notice; later "
        "cancellations are charged 100%.\n\nMessages, oldest first:\n[2026-10-14 08:00] inbound "
        '([CONTACT_1]):\n"""\nCan we move tomorrow\'s lesson to 5pm?\n"""',
        expect={"contains": ["[CONTACT_1"], "max_words": 120},
    ),
    *[
        Case(
            name=f"classify {intent}",
            prompt="inbox.classify",
            content=STYLE
            + f"Conversation: -\n\nMessages, oldest first:\n[2026-10-14 08:00] inbound "
            f'([CONTACT_1]):\n"""\n{message}\n"""',
            expect={"equals": {"intent": intent}},
        )
        for intent, message in (
            ("reschedule", "Could we move Thursday's lesson to Friday this week?"),
            ("billing", "I think I was charged twice on the October invoice."),
            ("complaint", "I'm really unhappy, the tutor was late three times."),
        )
    ],
    Case(
        name="thread summary",
        prompt="inbox.summary",
        content=STYLE
        + "Conversation: Lessons\n\nMessages, oldest first:\n[2026-10-13 08:00] inbound "
        '([CONTACT_1]):\n"""\nCan we move to Fridays?\n"""\n[2026-10-13 09:00] outbound '
        '([PERSON_1]):\n"""\nYes from next week, I will check with the tutor.\n"""',
        expect={"json_keys": ["summary", "action_items"], "non_empty": ["summary"]},
    ),
    Case(
        name="command: reschedule from next week",
        prompt="command.parse",
        tools="command",
        content=STYLE
        + TODAY
        + 'Instruction:\n"""\nMove [STUDENT_1_FIRST]\'s Thursday maths to 5pm from next '
        'week\n"""',
        tool_results={
            "find_students": {"students": [{"id": "s1", "name": "[STUDENT_1]"}]},
            "find_lessons": {
                "lessons": [
                    {
                        "id": "l1",
                        "title": "Maths",
                        "start": "2026-10-15T16:00",
                        "weekday": "thursday",
                        "minutes": 60,
                        "in_series": True,
                    },
                    {
                        "id": "l2",
                        "title": "Maths",
                        "start": "2026-10-22T16:00",
                        "weekday": "thursday",
                        "minutes": 60,
                        "in_series": True,
                    },
                ]
            },
            "propose_reschedule": {"proposal": 1, "summary": "Move Maths", "status": "waiting"},
        },
        expect={
            "tools_called": ["propose_reschedule"],
            "tool_args": {
                "propose_reschedule.lesson_id": "l2",
                "propose_reschedule.new_start": "*T17:00",
                "propose_reschedule.scope": "following",
            },
        },
    ),
    Case(
        name="command: tutor search",
        prompt="command.parse",
        tools="command",
        content=STYLE
        + TODAY
        + 'Instruction:\n"""\nFind a GCSE chemistry tutor free Tuesday evenings near LS6\n"""',
        tool_results={"search_tutors": {"search": 1, "status": "the user can open this search"}},
        expect={
            "tools_called": ["search_tutors"],
            "tool_args": {"search_tutors.weekday": "tuesday", "search_tutors.postcode": "LS6"},
        },
    ),
    Case(
        name="copilot: debtors",
        prompt="copilot.answer",
        tools="copilot",
        content=STYLE
        + TODAY
        + 'Question:\n"""\nWhat\'s our outstanding balance over 30 days?\n"""',
        tool_results={
            "list_reports": {
                "reports": [
                    {
                        "key": "aged_debtors",
                        "title": "Aged debtors",
                        "category": "finance",
                        "description": "What clients owe by age",
                        "group_by": [],
                        "period": False,
                    },
                    {
                        "key": "revenue",
                        "title": "Revenue",
                        "category": "finance",
                        "description": "Revenue by period",
                        "group_by": [],
                        "period": True,
                    },
                ]
            },
            "run_report": {
                "citation": 1,
                "report": "aged_debtors",
                "title": "Aged debtors",
                "period": {"from": "2026-10-01", "to": "2026-10-14"},
                "group_by": "",
                "columns": [
                    {"key": "client", "label": "Client", "type": "text"},
                    {"key": "days_31_60", "label": "31-60 days", "type": "money"},
                    {"key": "over_60", "label": "Over 60 days", "type": "money"},
                ],
                "rows": [
                    {
                        "client": "[CLIENT_1]",
                        "days_31_60": "120.00",
                        "over_60": "80.00",
                        "currency": "GBP",
                    }
                ],
                "total_rows": 1,
                "totals": [],
                "notes": [],
            },
        },
        expect={
            "tools_called": ["list_reports", "run_report"],
            "tool_args": {"run_report.report": "aged_debtors"},
            "contains": ["[1]"],
        },
    ),
    Case(
        name="broadcast draft",
        prompt="content.write",
        content=STYLE
        + 'Kind: broadcast\nBusiness: Bright Minds\nChannel: email (email)\n\nBrief:\n"""\n'
        'Half-term revision sessions for GCSE maths, 27-29 October, small groups.\n"""',
        expect={
            "json_keys": ["title", "subject", "body", "meta_description"],
            "non_empty": ["body"],
            "not_contains": ["guarantee"],
        },
    ),
    Case(
        name="tutor bio",
        prompt="content.write",
        content=STYLE
        + "Kind: bio\nBusiness: Bright Minds\nTutor: [TUTOR_1]\nHeadline: GCSE maths specialist\n"
        "Approved subjects: Maths GCSE, Physics GCSE\nLanguages: English\nYears of experience: 6\n"
        'Teaches: online\nCurrent public bio:\n"""\n\n"""\n\nBrief:\n"""\nWarm, patient, exam '
        'focused\n"""',
        expect={"non_empty": ["body"], "contains": ["[TUTOR_1"], "not_contains": ["oxford"]},
    ),
    Case(
        name="matching explanation",
        prompt="matching.explain",
        content=STYLE
        + "Tutor: [TUTOR_1] (GCSE maths specialist)\nRequest: Maths, mode online, area LS6\n"
        "Overall score: 86.5 out of 100\nDistance: unknown km\nRestricted: no\nScore breakdown "
        "(factor: weight, score 0-1, value, known):\n"
        + json.dumps(
            {
                "availability": {"weight": 3, "score": 1.0, "value": "all slots", "known": True},
                "rating": {"weight": 2, "score": 0.9, "value": "4.7", "known": True},
                "distance": {"weight": 1, "score": 0.5, "value": None, "known": False},
            },
            sort_keys=True,
        ),
        expect={
            "json_keys": ["explanation", "intro_message"],
            "contains": ["[TUTOR_1", "availab"],
        },
    ),
]

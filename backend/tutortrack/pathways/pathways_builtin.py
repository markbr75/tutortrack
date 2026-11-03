"""The ready-made pathways (E34 FR-34-1, T02): Apply for a job, Join a job, Finish a job.

Steps that need other tickets come later and arrive as a new ``version``: Family consents and
"information access ends" with T03 (consent), checks from the passport with T09.
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_noop as N_

from .builtin_pathways import builtin_pathway


@builtin_pathway(
    "apply_for_job",
    "apply",
    name=N_("Apply for a job"),
    description=N_(
        "Starts when a tutor applies for a job on the job board: questions, checks, a call, "
        "then staff choose."
    ),
)
def apply_for_job() -> dict[str, Any]:
    return {
        "record_type": "job",
        "stages": [
            {
                "key": "application",
                "name": N_("Your application"),
                "gate": "",
                "steps": [
                    {
                        "key": "questions",
                        "type": "questions",
                        "name": N_("Tell us about you and this job"),
                        "due_days": 3,
                        "config": {
                            "fields": [
                                {
                                    "key": "why",
                                    "label": N_("Why are you a good fit for this job?"),
                                    "type": "textarea",
                                    "required": True,
                                },
                                {
                                    "key": "experience",
                                    "label": N_("Experience with this subject and level"),
                                    "type": "textarea",
                                    "required": False,
                                },
                            ]
                        },
                    },
                    {
                        "key": "checks",
                        "type": "show_check",
                        "name": N_("Your checks are in date"),
                        "config": {"requirement": ""},
                    },
                ],
            },
            {
                "key": "call",
                "name": N_("A call with us"),
                "gate": "",
                "steps": [
                    {
                        "key": "call",
                        "type": "book_call",
                        "name": N_("Book a call"),
                        "due_days": 5,
                        "config": {"title": N_("Call about the job"), "minutes": 20, "days": 14},
                    }
                ],
            },
            {
                "key": "decision",
                "name": N_("Our decision"),
                "gate": "chosen",
                "steps": [
                    {
                        "key": "choose",
                        "type": "staff_review",
                        "assignee": "staff",
                        "name": N_("Choose this tutor"),
                        "due_days": 3,
                        "config": {"question": N_("Should this tutor get the job?")},
                    }
                ],
            },
        ],
    }


@builtin_pathway(
    "join_job",
    "join",
    name=N_("Join a job"),
    description=N_(
        "Starts when a tutor is put on a job or accepts it: the job agreement, checks and the "
        "handover. Until it is ready the tutor is joining, and lessons can't be confirmed."
    ),
)
def join_job() -> dict[str, Any]:
    return {
        "record_type": "job",
        "stages": [
            {
                "key": "before_first_lesson",
                "name": N_("Before your first lesson"),
                "gate": "ready",
                "steps": [
                    {
                        "key": "agreement",
                        "type": "sign",
                        "name": N_("Sign the job agreement"),
                        "due_days": 3,
                        "config": {
                            "title": N_("Job agreement"),
                            "text": N_(
                                "I agree to teach this job as arranged with the business, to "
                                "follow its policies, to keep information about the family "
                                "private and to use it only for this job, and to give notice "
                                "before I stop."
                            ),
                        },
                    },
                    {
                        "key": "checks",
                        "type": "show_check",
                        "name": N_("Your checks are in date"),
                        "config": {"requirement": ""},
                    },
                    {
                        "key": "handover",
                        "type": "acknowledge",
                        "name": N_("Read the handover and the safeguarding policy"),
                        "due_days": 3,
                        "config": {
                            "title": N_("Handover and safeguarding"),
                            "text": N_(
                                "Read the job's notes for tutors and the business's "
                                "safeguarding policy. Report any concern about a child's "
                                "safety the same day."
                            ),
                            "link": "",
                        },
                    },
                ],
            }
        ],
    }


@builtin_pathway(
    "finish_job",
    "finish",
    name=N_("Finish a job"),
    description=N_(
        "Starts when a tutor leaves a job or the job ends: a final report, resources back and "
        "a final check of pay."
    ),
)
def finish_job() -> dict[str, Any]:
    return {
        "record_type": "job",
        "stages": [
            {
                "key": "wrap_up",
                "name": N_("Wrapping up"),
                "gate": "",
                "steps": [
                    {
                        "key": "final_report",
                        "type": "questions",
                        "name": N_("Write a final report"),
                        "due_days": 7,
                        "config": {
                            "fields": [
                                {
                                    "key": "progress",
                                    "label": N_("Progress made during the job"),
                                    "type": "textarea",
                                    "required": True,
                                },
                                {
                                    "key": "next_steps",
                                    "label": N_("What the student should work on next"),
                                    "type": "textarea",
                                    "required": False,
                                },
                            ],
                            "review": True,
                        },
                    },
                    {
                        "key": "resources",
                        "type": "acknowledge",
                        "name": N_("Return resources"),
                        "due_days": 7,
                        "config": {
                            "title": N_("Return resources"),
                            "text": N_(
                                "Give back any books, equipment or resources you borrowed for "
                                "this job."
                            ),
                            "link": "",
                        },
                    },
                    {
                        "key": "final_pay",
                        "type": "staff_review",
                        "assignee": "staff",
                        "name": N_("Check the final pay"),
                        "due_days": 14,
                        "config": {
                            "question": N_("Is everything for this job paid or on a statement?")
                        },
                    },
                ],
            }
        ],
    }

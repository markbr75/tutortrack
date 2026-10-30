"""The step-type registry (E34 FR-34-1) and the first step types (T01).

A step type says who may do it (``assignees``), cleans its settings when a template is
saved (``clean``), records what the person did (``complete``, returning the step's
``result``), and says what the person doing it sees (``view``). Tutors' answers can wait for
staff to check them (``review``). System steps have a ``check`` instead, evaluated whenever
the run moves and once a day while open.

Other apps add step types in their own ``pathway_steps.py`` (autodiscovered):

    register_step_type(StepType(key="trial_lesson", label=..., assignees=("participant",), ...))
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.core.exceptions import BusinessRuleViolation

from .models import PathwayStep

PARTICIPANT, STAFF, FAMILY, SYSTEM = "participant", "staff", "family", "system"


@dataclass(frozen=True)
class Completion:
    """Someone finishing a step: the step, who they are, and what they sent."""

    step: PathwayStep
    user: Any
    payload: dict[str, Any]


@dataclass(frozen=True)
class StepType:
    key: str
    label: Any
    assignees: tuple[str, ...]
    clean: Callable[[dict[str, Any], str], dict[str, Any]]  # (config, record type) -> config
    complete: Callable[[Completion], dict[str, Any]] | None = None
    review: Callable[[dict[str, Any]], bool] = lambda config: False
    check: Callable[[PathwayStep], bool] | None = None
    view: Callable[[PathwayStep], dict[str, Any]] = lambda step: {}


_types: dict[str, StepType] = {}


def register_step_type(step_type: StepType) -> StepType:
    _types[step_type.key] = step_type
    return step_type


def step_type(key: str) -> StepType | None:
    return _types.get(key)


def step_types() -> list[StepType]:
    return list(_types.values())


# --- helpers ------------------------------------------------------------------------------------


def _text(config: dict[str, Any], key: str, *, limit: int, required: bool = False) -> str:
    value = config.get(key, "")
    if not isinstance(value, str):
        raise BusinessRuleViolation(_("%(field)s must be text.") % {"field": key})
    value = value.strip()
    if required and not value:
        raise BusinessRuleViolation(_("Add the %(field)s.") % {"field": key})
    if len(value) > limit:
        raise BusinessRuleViolation(
            _("%(field)s is too long (at most %(n)s characters).") % {"field": key, "n": limit}
        )
    return value


def _flag(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if not isinstance(value, bool):
        raise BusinessRuleViolation(_("%(field)s must be true or false.") % {"field": key})
    return value


def _link(config: dict[str, Any]) -> str:
    link = _text(config, "link", limit=500)
    if link and not link.startswith("https://"):
        raise BusinessRuleViolation(_("Links must start with https://."))
    return link


# --- questions ----------------------------------------------------------------------------------

QUESTION_TYPES = (
    "text", "textarea", "email", "phone", "number", "date", "select", "multiselect", "checkbox",
)  # fmt: skip
KEY = re.compile(r"[a-z][a-z0-9_]{0,39}")


def _clean_questions(config: dict[str, Any], record_type: str) -> dict[str, Any]:
    raw = config.get("fields")
    if not isinstance(raw, list) or not raw:
        raise BusinessRuleViolation(_("Add at least one question."))
    if len(raw) > 30:
        raise BusinessRuleViolation(_("A step can ask at most 30 questions."))
    fields: list[dict[str, Any]] = []
    keys: set[str] = set()
    for f in raw:
        if not isinstance(f, dict):
            raise BusinessRuleViolation(_("Each question needs a key, a label and a type."))
        key = str(f.get("key", ""))
        if not KEY.fullmatch(key) or key in keys:
            raise BusinessRuleViolation(_("Question keys must be unique, lower-case words."))
        keys.add(key)
        if f.get("type") not in QUESTION_TYPES:
            raise BusinessRuleViolation(_("Unknown question type: %(t)s") % {"t": f.get("type")})
        cleaned = {
            "key": key,
            "label": _text(f, "label", limit=200, required=True),
            "type": f["type"],
            "required": _flag(f, "required", False),
        }
        help_text = _text(f, "help", limit=500)
        if help_text:
            cleaned["help"] = help_text
        if f["type"] in ("select", "multiselect"):
            options = f.get("options")
            if not isinstance(options, list) or not options or len(options) > 50:
                raise BusinessRuleViolation(_("Give between 1 and 50 options."))
            cleaned["options"] = [str(o)[:200] for o in options]
        fields.append(cleaned)
    return {"fields": fields, "review": _flag(config, "review", False)}


def _complete_questions(c: Completion) -> dict[str, Any]:
    from tutortrack.leads.forms import clean_submission

    answers = c.payload.get("answers")
    if not isinstance(answers, dict):
        raise BusinessRuleViolation(_("Send the answers."))
    fields = c.step.config["fields"]
    cleaned = clean_submission({"steps": [{"fields": fields}]}, answers)
    for f in fields:  # options of multi-choice questions (clean_submission checks single ones)
        value = cleaned.get(f["key"])
        if (
            f["type"] == "multiselect"
            and value is not None
            and (not isinstance(value, list) or any(v not in f["options"] for v in value))
        ):
            raise BusinessRuleViolation(
                _("Check the form."), extra={"errors": {f["key"]: [_("Choose from the list.")]}}
            )
    return {"answers": cleaned}


register_step_type(
    StepType(
        key="questions",
        label=gettext_lazy("Answer questions"),
        assignees=(PARTICIPANT,),
        clean=_clean_questions,
        complete=_complete_questions,
        review=lambda config: bool(config.get("review")),
        view=lambda step: {"fields": step.config["fields"]},
    )
)


# --- upload a document --------------------------------------------------------------------------


def _clean_upload(config: dict[str, Any], record_type: str) -> dict[str, Any]:
    max_files = config.get("max_files", 3)
    if not isinstance(max_files, int) or isinstance(max_files, bool) or not 1 <= max_files <= 10:
        raise BusinessRuleViolation(_("Allow between 1 and 10 files."))
    return {
        "instructions": _text(config, "instructions", limit=2000),
        "max_files": max_files,
        "verify": _flag(config, "verify", True),
    }


def _complete_upload(c: Completion) -> dict[str, Any]:
    from tutortrack.core.models import StoredFile
    from tutortrack.core.storage.services import attach

    ids = c.payload.get("files")
    if not isinstance(ids, list) or not ids:
        raise BusinessRuleViolation(_("Upload at least one file."))
    if len(ids) > c.step.config["max_files"]:
        raise BusinessRuleViolation(
            _("Add at most %(n)s files.") % {"n": c.step.config["max_files"]}
        )
    files = list(
        StoredFile.objects.filter(
            pk__in=[str(i) for i in ids],
            uploaded_by=c.user,
            status=StoredFile.Status.UPLOADED,
        ).exclude(scan_status=StoredFile.ScanStatus.INFECTED)
    )
    if len(files) != len(set(map(str, ids))):
        raise BusinessRuleViolation(_("Upload the files again: some weren't found."))
    for stored in files:
        attach(stored, c.step)
    return {"files": [{"id": str(f.pk), "filename": f.filename} for f in files]}


register_step_type(
    StepType(
        key="upload",
        label=gettext_lazy("Upload a document"),
        assignees=(PARTICIPANT,),
        clean=_clean_upload,
        complete=_complete_upload,
        review=lambda config: bool(config.get("verify", True)),
        view=lambda step: {
            "instructions": step.config["instructions"],
            "max_files": step.config["max_files"],
        },
    )
)


# --- sign an agreement --------------------------------------------------------------------------


def _clean_sign(config: dict[str, Any], record_type: str) -> dict[str, Any]:
    return {
        "title": _text(config, "title", limit=200, required=True),
        "text": _text(config, "text", limit=20000, required=True),
    }


def _complete_sign(c: Completion) -> dict[str, Any]:
    from tutortrack.crm import signing

    tutor = c.step.run.tutor
    if tutor is None:
        raise BusinessRuleViolation(_("Only a tutor can sign this."))
    full_name = str(c.payload.get("full_name", "")).strip()
    if not full_name or len(full_name) > 200:
        raise BusinessRuleViolation(_("Type your full name to sign."))
    signature = signing.sign_agreement(
        tutor=tutor,
        key=f"pathway:{c.step.pk}",
        title=c.step.config["title"],
        text=c.step.config["text"],
        signer=c.user,
        full_name=full_name,
    )
    return {"signature_id": str(signature.pk), "signed_as": full_name}


register_step_type(
    StepType(
        key="sign",
        label=gettext_lazy("Sign an agreement"),
        assignees=(PARTICIPANT,),
        clean=_clean_sign,
        complete=_complete_sign,
        view=lambda step: {"title": step.config["title"], "text": step.config["text"]},
    )
)


# --- read and acknowledge -----------------------------------------------------------------------


def _clean_acknowledge(config: dict[str, Any], record_type: str) -> dict[str, Any]:
    cleaned = {
        "title": _text(config, "title", limit=200, required=True),
        "text": _text(config, "text", limit=20000),
        "link": _link(config),
    }
    if not cleaned["text"] and not cleaned["link"]:
        raise BusinessRuleViolation(_("Add the text to read, or a link to it."))
    return cleaned


register_step_type(
    StepType(
        key="acknowledge",
        label=gettext_lazy("Read and acknowledge"),
        assignees=(PARTICIPANT,),
        clean=_clean_acknowledge,
        complete=lambda c: {"acknowledged": True},
        view=lambda step: dict(step.config),
    )
)


# --- staff review -------------------------------------------------------------------------------


def _clean_review(config: dict[str, Any], record_type: str) -> dict[str, Any]:
    return {"question": _text(config, "question", limit=300)}


def _complete_review(c: Completion) -> dict[str, Any]:
    return {"decision": "approved", "note": str(c.payload.get("note", ""))[:2000]}


register_step_type(
    StepType(
        key="staff_review",
        label=gettext_lazy("Staff review"),
        assignees=(STAFF,),
        clean=_clean_review,
        complete=_complete_review,
        view=lambda step: {"question": step.config["question"]},
    )
)


# --- system check -------------------------------------------------------------------------------


def _clean_check(config: dict[str, Any], record_type: str) -> dict[str, Any]:
    from tutortrack.automations.conditions import questions

    key = config.get("question")
    known = {q["key"]: q["subject"] for q in questions()}
    if key not in known:
        raise BusinessRuleViolation(_("Choose a question TutorTrack can check."))
    if known[key] != record_type:
        raise BusinessRuleViolation(_("That question is about a different kind of record."))
    return {"question": key}


def _check(step: PathwayStep) -> bool:
    from tutortrack.automations import registry
    from tutortrack.automations.conditions import evaluate
    from tutortrack.automations.services import build_context

    run = step.run
    subject = registry.subject(run.subject_type)
    record = subject.load(run.subject_id) if subject else None
    if subject is None or record is None:
        return False
    return evaluate({"predicate": step.config["question"]}, build_context(subject, record))


def _question_label(step: PathwayStep) -> dict[str, Any]:
    from tutortrack.automations.conditions import questions

    labels = {q["key"]: q["label"] for q in questions()}
    return {"question": labels.get(step.config["question"], step.config["question"])}


register_step_type(
    StepType(
        key="system_check",
        label=gettext_lazy("TutorTrack checks"),
        assignees=(SYSTEM,),
        clean=_clean_check,
        check=_check,
        view=_question_label,
    )
)

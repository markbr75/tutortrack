"""``FakeLLMProvider``: deterministic canned responses for every prompt, including
multi-turn tool use, so the tool loop, permission checks, metering and redaction are
tested without the network (and local development works without an API key).

Responses are derived from the (redacted) request, so placeholders flow through exactly
as they would with the real model. Tests can also ``script`` exact responses per prompt
and inspect ``requests`` (what would have been sent).
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

from .base import LLMRequest, LLMResponse, Tier, ToolCall, Usage

PLACEHOLDER = re.compile(r"\[([A-Z]+)_(\d+)(_FIRST|_LAST)?\]")
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
SUBJECTS = ["maths", "english", "science", "chemistry", "physics", "biology", "french", "spanish"]
LEVEL_RE = re.compile(r"\b(GCSE|A[- ]level|KS[1-5]|Year \d{1,2}|11\+|SAT)\b", re.IGNORECASE)
POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?(?: ?\d[A-Z]{2})?)\b")
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.IGNORECASE)

Handler = Callable[[LLMRequest], LLMResponse]


# --- request helpers --------------------------------------------------------------------------


def first_user_text(request: LLMRequest) -> str:
    content = request.messages[0]["content"] if request.messages else ""
    return content if isinstance(content, str) else ""


def tool_results(request: LLMRequest) -> list[dict[str, Any]]:
    """Every tool result so far, oldest first, with its decoded JSON body."""
    out = []
    for message in request.messages[1:]:
        if message["role"] != "user" or not isinstance(message["content"], list):
            continue
        for block in message["content"]:
            if block.get("type") == "tool_result":
                try:
                    body = json.loads(block.get("content") or "{}")
                except ValueError:
                    body = {}
                out.append({"is_error": bool(block.get("is_error")), "body": body})
    return out


def placeholders(text: str, kind: str = "", *, first: bool | None = None) -> list[str]:
    found = []
    for match in PLACEHOLDER.finditer(text):
        if kind and match.group(1) != kind:
            continue
        if first is not None and (match.group(3) == "_FIRST") != first:
            continue
        if first is False and match.group(3) == "_LAST":
            continue
        if match.group(0) not in found:
            found.append(match.group(0))
    return found


def section(text: str, heading: str) -> str:
    """The quoted block after ``heading`` in a user message."""
    index = text.find(heading)
    if index < 0:
        return ""
    rest = text[index + len(heading) :]
    match = re.search(r'"""\n(.*?)\n"""', rest, re.DOTALL)
    return match.group(1) if match else rest.strip()


def _usage(request: LLMRequest, text: str, seen: set[str]) -> Usage:
    sent = len(json.dumps(request.messages, default=str)) // 4
    system = len(request.system) // 4
    cached = request.prompt in seen
    seen.add(request.prompt)
    return Usage(
        input_tokens=sent,
        output_tokens=len(text) // 4 + 40,
        cache_read_tokens=system if cached else 0,
        cache_write_tokens=0 if cached else system,
    )


def text_response(text: str) -> dict[str, Any]:
    return {"text": text}


def json_response(data: Any) -> dict[str, Any]:
    return {"text": json.dumps(data)}


def tool_response(name: str, arguments: dict[str, Any], note: str = "") -> dict[str, Any]:
    return {"tool": (name, arguments), "text": note}


# --- schema filling -----------------------------------------------------------------------------


def fill(schema: dict[str, Any], key: str, phrase: str) -> Any:
    if "enum" in schema:
        values = [v for v in schema["enum"] if v not in ("", 0)] or schema["enum"]
        return values[0] if values else ""
    kind = schema.get("type")
    if kind == "object":
        return {k: fill(v, k, phrase) for k, v in schema.get("properties", {}).items()}
    if kind == "array":
        items = schema.get("items", {})
        if "enum" in items:
            return list(items["enum"][:1])
        return [fill(items, key, phrase)]
    if kind == "integer":
        return 80
    if kind == "boolean":
        return False
    return f"{key.replace('_', ' ').capitalize()}: {phrase}".strip()


# --- per-prompt handlers ------------------------------------------------------------------------


def lesson_report(request: LLMRequest) -> dict[str, Any]:
    text = first_user_text(request)
    student = (placeholders(text, "STUDENT", first=True) or ["The student"])[0]
    notes = section(text, "Tutor's notes:") or section(text, "Voice note transcript:")
    phrase = f"{student} worked on {notes[:160]}".strip()
    data = fill(request.output_schema or {}, "answers", phrase)
    data["homework"] = "Complete the practice questions from today's lesson."
    return json_response(data)


def progress_summary(request: LLMRequest) -> dict[str, Any]:
    text = first_user_text(request)
    student = (
        placeholders(text, "STUDENT", first=True) or placeholders(text, "STUDENT") or ["Your child"]
    )[0]
    attended = re.search(r'"attended": (\d+)', text)
    lessons = re.search(r'"lessons": (\d+)', text)
    count = f"{attended.group(1)} of {lessons.group(1)}" if attended and lessons else "all"
    return text_response(
        f"{student} has made steady progress this term and attended {count} lessons.\n\n"
        f"Next, {student} should keep practising the topics marked as learning.\n\n"
        "At home, a short regular review of homework will help."
    )


def parent_rewrite(request: LLMRequest) -> dict[str, Any]:
    text = first_user_text(request)
    body = section(text, "Text:")
    language = re.search(r"Target language: (.*)", text)
    target = language.group(1).strip() if language else ""
    plain = body.replace("KS3", "Key Stage 3 (ages 11 to 14)").replace(
        "AO2", "using what they know"
    )
    if target and "same language" not in target and "English" not in target:
        plain = f"({target}) {plain}"
    return json_response({"text": plain, "language": target})


def enquiry_extract(request: LLMRequest) -> dict[str, Any]:
    text = section(first_user_text(request), "Enquiry text:")
    lower = text.lower()
    contact = re.search(r"(?:I'm|I am|my name is)\s+([A-Z][a-z]+)(?:\s+([A-Z][a-z]+))?", text)
    children = re.findall(r"(?:my|our) (?:son|daughter|child)\s+([A-Z][a-z]+)", text)
    levels = LEVEL_RE.findall(text)
    subjects = [
        {"subject": s.capitalize(), "level": levels[0] if levels else ""}
        for s in SUBJECTS
        if s in lower
    ]
    availability = [
        m.group(0)
        for m in re.finditer(r"\b(?:" + "|".join(WEEKDAYS) + r")s?\b[^.,;]*", text, re.IGNORECASE)
    ]
    postcode = POSTCODE_RE.search(text)
    mode = "online" if "online" in lower else ("in_person" if "in person" in lower else "")
    urgent = any(w in lower for w in ("urgent", "asap", "exam next", "mock"))
    return json_response(
        {
            "contact": {
                "first_name": contact.group(1) if contact else "",
                "last_name": (contact.group(2) or "") if contact else "",
                "email": (placeholders(text, "EMAIL") or [""])[0],
                "phone": (placeholders(text, "PHONE") or [""])[0],
            },
            "students": [
                {"first_name": c, "last_name": "", "year_group": "", "school": ""} for c in children
            ],
            "subjects": subjects,
            "availability": availability,
            "location": {
                "postcode": postcode.group(1) if postcode else "",
                "area": "",
                "mode": mode,
            },
            "urgency": "high" if urgent else "normal",
            "summary": text[:200],
        }
    )


def enquiry_triage(request: LLMRequest) -> dict[str, Any]:
    text = first_user_text(request)
    contact = (
        placeholders(text, "CONTACT", first=True) or placeholders(text, "CONTACT") or ["there"]
    )[0]
    urgent = '"urgency": "high"' in text
    return json_response(
        {
            "next_steps": [
                "Call the family to confirm availability",
                "Shortlist matching tutors",
                "Offer a trial lesson",
            ],
            "priority": "high" if urgent else "normal",
            "reply_subject": "Your tuition enquiry",
            "reply_body": f"Dear {contact},\n\nThank you for getting in touch. We'd love to "
            "help. Could you tell us which days and times suit you best? We'll then suggest "
            "a tutor and a trial lesson.",
        }
    )


def inbox_reply(request: LLMRequest) -> dict[str, Any]:
    text = first_user_text(request)
    who = (
        placeholders(text, "CONTACT", first=True)
        or placeholders(text, "CONTACT")
        or placeholders(text, "PERSON", first=True)
        or ["there"]
    )[0]
    lesson = re.search(r"Upcoming lesson: (.*)", text)
    extra = f" Your next lesson is {lesson.group(1)}." if lesson else ""
    return text_response(
        f"Hi {who}, thanks for your message.{extra} We'll confirm the details shortly."
    )


def inbox_classify(request: LLMRequest) -> dict[str, Any]:
    lower = first_user_text(request).lower()
    rules = [
        ("cancellation", ("cancel", "stop lessons")),
        ("reschedule", ("move", "reschedule", "different time", "change the time")),
        ("billing", ("invoice", "pay", "bill", "refund", "charge")),
        ("complaint", ("unhappy", "complain", "disappointed")),
        ("new_enquiry", ("looking for", "enquir", "new tutor")),
        ("feedback", ("thank", "great", "brilliant")),
    ]
    for intent, words in rules:
        if any(w in lower for w in words):
            return json_response(
                {"intent": intent, "confidence": 85, "reason": f"Mentions {words[0]}."}
            )
    return json_response({"intent": "other", "confidence": 40, "reason": "No clear intent."})


def inbox_summary(request: LLMRequest) -> dict[str, Any]:
    text = first_user_text(request)
    count = text.count('"""\n') // 1
    who = (placeholders(text, "CONTACT") or placeholders(text, "PERSON") or ["The family"])[0]
    return json_response(
        {
            "summary": f"{who} and the team exchanged {count} messages about lessons.",
            "action_items": ["Reply to the latest message"],
        }
    )


def _time_from(text: str) -> tuple[int, int] | None:
    match = TIME_RE.search(text)
    if not match:
        return None
    hour = int(match.group(1)) % 12 + (12 if match.group(3).lower() == "pm" else 0)
    return hour, int(match.group(2) or 0)


def command(request: LLMRequest) -> dict[str, Any]:
    text = first_user_text(request)
    instruction = section(text, "Instruction:")
    lower = instruction.lower()
    results = tool_results(request)
    if any(r["is_error"] for r in results):
        return text_response(f"I couldn't do that: {results[-1]['body'].get('error', '')}")
    if "tutor" in lower and ("find" in lower or "search" in lower):
        if results:
            return text_response("I've set up a tutor search for you to open.")
        level = LEVEL_RE.search(instruction)
        subject = next((s for s in SUBJECTS if s in lower), "")
        weekday = next((d for d in WEEKDAYS if d in lower), "")
        postcode = POSTCODE_RE.search(instruction)
        evening = "evening" in lower
        return tool_response(
            "search_tutors",
            {
                "subject": subject,
                "level": level.group(1) if level else "",
                "mode": "online" if "online" in lower else "either",
                "postcode": postcode.group(1) if postcode else "",
                "weekday": weekday,
                "after_time": "17:00" if evening else "",
                "before_time": "21:00" if evening else "",
            },
        )
    if "remind" in lower or "task" in lower:
        if results:
            return text_response("I've proposed a task for you to confirm.")
        today = timezone.now().date()
        due = (today + timedelta(days=1)).isoformat() if "tomorrow" in lower else ""
        title = re.sub(r"^(remind me to|add a task to)\s+", "", instruction, flags=re.IGNORECASE)
        return tool_response("propose_task", {"title": title[:120], "due_date": due, "notes": ""})
    if "move" in lower or "reschedule" in lower:
        if not results:
            name = (placeholders(instruction, "STUDENT") or [""])[0]
            if not name:
                capital = re.findall(r"\b([A-Z][a-z]+)", instruction[1:])
                name = capital[0] if capital else ""
            return tool_response("find_students", {"name": name})
        last = results[-1]["body"]
        if "students" in last:
            students = last["students"]
            if not students:
                return text_response("I couldn't find that student.")
            weekday = next((d for d in WEEKDAYS if d in lower), "")
            subject = next((s for s in SUBJECTS if s in lower), "")
            return tool_response(
                "find_lessons",
                {
                    "student_id": students[0]["id"],
                    "weekday": weekday,
                    "subject": subject,
                    "from_date": "",
                },
            )
        if "lessons" in last:
            lessons = last["lessons"]
            if not lessons:
                return text_response("I couldn't find a matching lesson.")
            lesson = lessons[1] if "next week" in lower and len(lessons) > 1 else lessons[0]
            start = datetime.fromisoformat(lesson["start"])
            hour_minute = _time_from(instruction) or (start.hour, start.minute)
            new_start = start.replace(hour=hour_minute[0], minute=hour_minute[1])
            following = any(w in lower for w in ("from next week", "onwards", "every", "from now"))
            return tool_response(
                "propose_reschedule",
                {
                    "lesson_id": lesson["id"],
                    "new_start": new_start.strftime("%Y-%m-%dT%H:%M"),
                    "scope": "following" if following else "this",
                },
            )
        return text_response("I've proposed the change for you to confirm.")
    return text_response(
        "I couldn't work out what to do. Try \"Move Sam's Thursday lesson to 5pm\"."
    )


COPILOT_TOPICS = [
    (("owe", "outstanding", "balance", "debt", "overdue"), "aged_debtors"),
    (("cancel",), "cancellations"),
    (("revenue", "income", "sales"), "revenue"),
    (("attendance",), "attendance"),
    (("enquir", "lead"), "enquiry_funnel"),
    (("lesson",), "lessons"),
]


def copilot(request: LLMRequest) -> dict[str, Any]:
    question = section(first_user_text(request), "Question:").lower()
    results = tool_results(request)
    if not results:
        return tool_response("list_reports", {})
    last = results[-1]["body"]
    if "reports" in last:
        available = {r["key"]: r for r in last["reports"]}
        key = next(
            (
                k
                for words, k in COPILOT_TOPICS
                if k in available and any(w in question for w in words)
            ),
            next(iter(available), ""),
        )
        if not key:
            return text_response("You don't have access to any reports that answer this.")
        groups = [g["value"] for g in available[key].get("group_by", [])]
        group = "tutor" if "tutor" in question and "tutor" in groups else ""
        period = (
            "last_quarter"
            if ("last term" in question or "quarter" in question)
            else ("last_month" if "last month" in question else "this_month")
        )
        return tool_response(
            "run_report",
            {
                "report": key,
                "period": period,
                "from_date": "",
                "to_date": "",
                "group_by": group,
                "ordering": "",
            },
        )
    if results[-1]["is_error"]:
        return text_response(f"I couldn't run that report: {last.get('error', '')}")
    rows = last.get("rows") or []
    top = ""
    if rows:
        first = rows[0]
        label = first.get("group") or first.get("client") or first.get("tutor") or ""
        top = f" The first row is {label}." if label else ""
    return text_response(
        f"According to {last.get('title', 'the report')} [{last.get('citation', 1)}], there are "
        f"{last.get('total_rows', 0)} rows for {last.get('period', {}).get('from', '')} to "
        f"{last.get('period', {}).get('to', '')}.{top}"
    )


def content(request: LLMRequest) -> dict[str, Any]:
    text = first_user_text(request)
    kind = re.search(r"Kind: (\w+)", text)
    brief = section(text, "Brief:")[:200]
    tutor = (placeholders(text, "TUTOR", first=True) or placeholders(text, "TUTOR") or ["I"])[0]
    kind_name = kind.group(1) if kind else "broadcast"
    if kind_name == "broadcast":
        sms = "Channel: sms" in text
        body = (
            "Hi {{ recipient.first_name }}, " + brief[:120]
            if sms
            else "Hi {{ recipient.first_name }},\n\n"
            + brief
            + "\n\nBest wishes,\n{{ organisation.name }}"
        )
        return json_response(
            {
                "title": "",
                "subject": "" if sms else "News from us",
                "body": body,
                "meta_description": "",
            }
        )
    if kind_name == "bio":
        return json_response(
            {
                "title": f"{tutor}: patient, exam-focused tutor",
                "subject": "",
                "body": f"Hello, I'm {tutor}. {brief}",
                "meta_description": "",
            }
        )
    if kind_name == "page":
        return json_response(
            {
                "title": "About our tutoring",
                "subject": "",
                "body": f"{brief}\n\nGet in touch to book a trial lesson.",
                "meta_description": brief[:150],
            }
        )
    return json_response(
        {
            "title": "Tutor wanted",
            "subject": "",
            "body": f"We're looking for a tutor. {brief}",
            "meta_description": "",
        }
    )


def matching(request: LLMRequest) -> dict[str, Any]:
    text = first_user_text(request)
    tutor = (
        placeholders(text, "TUTOR", first=True) or placeholders(text, "TUTOR") or ["This tutor"]
    )[0]
    breakdown_line = text.split("Score breakdown", 1)[-1].split("\n", 1)[-1]
    try:
        breakdown = json.loads(breakdown_line)
    except ValueError:
        breakdown = {}
    ranked = sorted(
        breakdown.items(),
        key=lambda kv: -float(kv[1].get("weight", 0)) * float(kv[1].get("score", 0)),
    )
    top = ", ".join(k for k, _v in ranked[:2]) or "the overall fit"
    return json_response(
        {
            "explanation": f"{tutor} ranks highly mainly because of {top}.",
            "intro_message": f"We'd like to introduce {tutor}, who we think is a great fit.",
        }
    )


HANDLERS: dict[str, Callable[[LLMRequest], dict[str, Any]]] = {
    "lesson_report.draft": lesson_report,
    "progress.summary": progress_summary,
    "parent.rewrite": parent_rewrite,
    "enquiry.extract": enquiry_extract,
    "enquiry.triage": enquiry_triage,
    "inbox.reply": inbox_reply,
    "inbox.classify": inbox_classify,
    "inbox.summary": inbox_summary,
    "command.parse": command,
    "copilot.answer": copilot,
    "content.write": content,
    "matching.explain": matching,
}


class FakeLLMProvider:
    name = "fake"

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []
        self._scripted: dict[str, list[LLMResponse]] = {}
        self._cached: set[str] = set()
        self._calls = 0

    def model_for(self, tier: Tier) -> str:
        return str(settings.AI["MODEL_FAST" if tier == "fast" else "MODEL_DEFAULT"])

    def reset(self) -> None:
        self.requests.clear()
        self._scripted.clear()
        self._cached.clear()

    def script(self, prompt: str, *responses: LLMResponse) -> None:
        """Queue exact responses for ``prompt`` (consumed before the canned handler)."""
        self._scripted.setdefault(prompt, []).extend(responses)

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        queue = self._scripted.get(request.prompt)
        if queue:
            return queue.pop(0)
        handler = HANDLERS.get(request.prompt)
        spec = handler(request) if handler else text_response("OK")
        self._calls += 1
        text = str(spec.get("text") or "")
        model = self.model_for(request.tier)
        if "tool" in spec:
            name, arguments = spec["tool"]
            call = ToolCall(f"toolu_fake_{self._calls}", name, arguments)
            content: list[dict[str, Any]] = []
            if text:
                content.append({"type": "text", "text": text})
            content.append({"type": "tool_use", "id": call.id, "name": name, "input": arguments})
            return LLMResponse(
                text=text,
                stop_reason="tool_use",
                usage=_usage(request, json.dumps(arguments), self._cached),
                model=model,
                tool_calls=[call],
                content=content,
                request_id=f"req_fake_{self._calls}",
            )
        return LLMResponse(
            text=text,
            stop_reason="end_turn",
            usage=_usage(request, text, self._cached),
            model=model,
            content=[{"type": "text", "text": text}],
            request_id=f"req_fake_{self._calls}",
        )

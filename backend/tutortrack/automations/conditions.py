"""The condition evaluator (E14-T02): a JSON tree, interpreted without ``eval``.

    {"all": [cond, ...]}  {"any": [cond, ...]}  {"not": cond}
    {"field": "student.status", "op": "equals", "value": "active"}
    {"predicate": "first_lesson_for_student"}

Fields are dot paths into the whitelisted context (``registry.Subject.fields``) plus
``event.*``. ``changed``, ``changed_from`` and ``changed_to`` read the event's changes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils.dateparse import parse_date, parse_datetime

OPERATORS = (
    "equals", "not_equals", "in", "not_in", "contains", "not_contains", "gt", "gte", "lt",
    "lte", "is_empty", "is_not_empty", "changed", "changed_from", "changed_to",
    "within_last_days", "older_than_days", "within_next_days",
)  # fmt: skip
NO_VALUE = {"is_empty", "is_not_empty", "changed"}
MAX_DEPTH = 5

Predicate = Callable[[dict[str, Any]], bool]
_predicates: dict[str, tuple[str, Predicate]] = {}


class InvalidCondition(ValueError):
    pass


def register_predicate(key: str, label: str, fn: Predicate) -> None:
    _predicates[key] = (label, fn)


def predicates() -> dict[str, str]:
    return {k: label for k, (label, _fn) in _predicates.items()}


def resolve(context: dict[str, Any], path: str) -> Any:
    value: Any = context
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _num(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _when(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).astimezone()
    if isinstance(value, str):
        parsed = parse_datetime(value)
        if parsed is not None:
            return parsed if parsed.tzinfo else parsed.astimezone()
        day = parse_date(value)
        if day is not None:
            return datetime.combine(day, datetime.min.time()).astimezone()
    return None


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _compare(op: str, left: Any, right: Any) -> bool:
    a, b = _num(left), _num(right)
    if a is not None and b is not None:
        pair: tuple[Any, Any] = (a, b)
    else:
        da, db = _when(left), _when(right)
        if da is None or db is None:
            return False
        pair = (da, db)
    return {
        "gt": pair[0] > pair[1],
        "gte": pair[0] >= pair[1],
        "lt": pair[0] < pair[1],
        "lte": pair[0] <= pair[1],
    }[op]


def _same(left: Any, right: Any) -> bool:
    a, b = _num(left), _num(right)
    if a is not None and b is not None:
        return a == b
    if isinstance(left, str) and isinstance(right, str):
        return left.strip().lower() == right.strip().lower()
    return bool(left == right)


def _contains(container: Any, item: Any) -> bool:
    if isinstance(container, list):
        return any(_same(x, item) for x in container)
    if isinstance(container, str) and isinstance(item, str):
        return item.lower() in container.lower()
    return False


def _field(cond: dict[str, Any], context: dict[str, Any], now: datetime) -> bool:
    path, op, value = cond.get("field", ""), cond.get("op", ""), cond.get("value")
    if op not in OPERATORS:
        raise InvalidCondition(f"Unknown operator {op!r}")
    if op in ("changed", "changed_from", "changed_to"):
        changes = (context.get("event") or {}).get("changes") or {}
        name = path.split(".")[-1]
        if name not in changes:
            return False
        before, after = [*list(changes[name]), None, None][:2]
        if op == "changed":
            return True
        return _same(before if op == "changed_from" else after, value)
    actual = resolve(context, path)
    if op == "equals":
        return _same(actual, value)
    if op == "not_equals":
        return not _same(actual, value)
    if op in ("in", "not_in"):
        options = value if isinstance(value, list) else [value]
        found = any(_same(actual, o) for o in options)
        return found if op == "in" else not found
    if op == "contains":
        return _contains(actual, value)
    if op == "not_contains":
        return not _contains(actual, value)
    if op in ("gt", "gte", "lt", "lte"):
        return _compare(op, actual, value)
    if op == "is_empty":
        return _empty(actual)
    if op == "is_not_empty":
        return not _empty(actual)
    moment = _when(actual)
    days = _num(value)
    if moment is None or days is None:
        return False
    span = timedelta(days=float(days))
    if op == "within_last_days":
        return now - span <= moment <= now
    if op == "older_than_days":
        return moment < now - span
    return now <= moment <= now + span  # within_next_days


def evaluate(
    cond: dict[str, Any] | None, context: dict[str, Any], *, now: datetime | None = None,
    _depth: int = 0,
) -> bool:  # fmt: skip
    """True when ``cond`` holds (an empty condition always holds)."""
    from tutortrack.core.time import now as current

    if not cond:
        return True
    if _depth > MAX_DEPTH:
        raise InvalidCondition("Conditions are nested too deeply.")
    moment = now or current()
    if "all" in cond:
        return all(evaluate(c, context, now=moment, _depth=_depth + 1) for c in cond["all"])
    if "any" in cond:
        return any(evaluate(c, context, now=moment, _depth=_depth + 1) for c in cond["any"])
    if "not" in cond:
        return not evaluate(cond["not"], context, now=moment, _depth=_depth + 1)
    if "predicate" in cond:
        entry = _predicates.get(cond["predicate"])
        if entry is None:
            raise InvalidCondition(f"Unknown predicate {cond['predicate']!r}")
        return bool(entry[1](context))
    if "field" in cond:
        return _field(cond, context, moment)
    raise InvalidCondition("A condition needs all, any, not, field or predicate.")


def validate(cond: dict[str, Any] | None, paths: set[str], _depth: int = 0) -> list[str]:
    """Problems with a condition tree (unknown fields, operators, predicates)."""
    if not cond:
        return []
    if not isinstance(cond, dict):
        return ["A condition must be an object."]
    if _depth > MAX_DEPTH:
        return ["Conditions are nested too deeply."]
    errors: list[str] = []
    for key in ("all", "any"):
        if key in cond:
            if not isinstance(cond[key], list):
                return [f"'{key}' needs a list."]
            for child in cond[key]:
                errors += validate(child, paths, _depth + 1)
            return errors
    if "not" in cond:
        return validate(cond["not"], paths, _depth + 1)
    if "predicate" in cond:
        return [] if cond["predicate"] in _predicates else [f"Unknown check {cond['predicate']}"]
    path = cond.get("field")
    if not path:
        return ["A condition needs all, any, not, field or predicate."]
    if not (path in paths or path.startswith("event.")):
        errors.append(f"Unknown field {path}")
    if cond.get("op") not in OPERATORS:
        errors.append(f"Unknown operator {cond.get('op')}")
    elif cond.get("op") not in NO_VALUE and "value" not in cond:
        errors.append(f"{path}: give a value")
    return errors

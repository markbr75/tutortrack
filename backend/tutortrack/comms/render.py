"""Sandboxed template rendering (FR-13-3).

Templates are Jinja2 in a ``SandboxedEnvironment``: no access to private attributes or
unsafe methods, and contexts are plain dicts of whitelisted values built per type (never
model instances). Text is rendered unescaped; the HTML email part escapes it.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from functools import cache
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from babel.dates import format_date, format_datetime, format_time
from babel.numbers import format_currency
from jinja2 import ChainableUndefined, TemplateError, pass_context
from jinja2.runtime import Context
from jinja2.sandbox import SandboxedEnvironment


class TemplateInvalid(ValueError):
    pass


def _locale(ctx_locale: str | None) -> str:
    return (ctx_locale or "en-GB").replace("-", "_")


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


@cache
def _env() -> SandboxedEnvironment:
    env = SandboxedEnvironment(autoescape=False, undefined=ChainableUndefined)

    def loc(ctx: Context) -> str:
        return str(ctx.get("_locale") or "en_GB")

    def zone(ctx: Context, tz: str | None) -> ZoneInfo | None:
        name = tz or ctx.get("_timezone")
        return ZoneInfo(name) if name else None

    @pass_context
    def f_datetime(ctx: Context, value: Any, style: str = "medium", tz: str | None = None) -> str:
        moment = _as_datetime(value)
        if moment is None:
            return ""
        return str(format_datetime(moment, style, tzinfo=zone(ctx, tz), locale=loc(ctx)))

    @pass_context
    def f_time(ctx: Context, value: Any, tz: str | None = None) -> str:
        moment = _as_datetime(value)
        if moment is None:
            return ""
        return str(format_time(moment, "short", tzinfo=zone(ctx, tz), locale=loc(ctx)))

    @pass_context
    def f_date(ctx: Context, value: Any, style: str = "medium") -> str:
        if isinstance(value, str):
            try:
                value = date.fromisoformat(value[:10])
            except ValueError:
                return value
        if not isinstance(value, date):
            return ""
        return str(format_date(value, style, locale=loc(ctx)))

    @pass_context
    def f_money(ctx: Context, value: Any) -> str:
        if not isinstance(value, dict) or "amount" not in value:
            return ""
        amount = Decimal(str(value["amount"]))
        return str(format_currency(amount, value["currency"], locale=loc(ctx)))

    env.filters.update(datetime=f_datetime, time=f_time, date=f_date, money=f_money)
    return env


def validate(source: str) -> None:
    try:
        _env().parse(source)
    except TemplateError as exc:
        raise TemplateInvalid(str(exc)) from exc


def render(
    source: str, context: dict[str, Any], *, locale: str | None = None, timezone: str = ""
) -> str:
    """Render with ``|datetime``, ``|time``, ``|date`` and ``|money`` filters (dates shown in
    ``timezone`` unless a filter names one)."""
    try:
        template = _env().from_string(source)
        return template.render(**context, _locale=_locale(locale), _timezone=timezone).strip()
    except TemplateError as exc:
        raise TemplateInvalid(str(exc)) from exc


def to_html(text: str, *, organisation: str, footer: str = "") -> str:
    """A simple branded HTML version of a plain-text email body."""
    paragraphs = "".join(
        f"<p>{escape(block).replace(chr(10), '<br>')}</p>" for block in text.split("\n\n") if block
    )
    foot = f'<p style="color:#6b7280;font-size:12px">{footer}</p>' if footer else ""
    return (
        '<div style="font-family:Arial,sans-serif;font-size:15px;color:#111827;'
        'max-width:600px;margin:0 auto">'
        f'<p style="font-weight:bold;font-size:17px">{escape(organisation)}</p>'
        f"{paragraphs}{foot}</div>"
    )


def sms_segments(text: str) -> int:
    """GSM-7 messages split at 153 chars per part (160 alone); others at 67 (70 alone)."""
    gsm = all(ord(c) < 128 for c in text)
    single, multi = (160, 153) if gsm else (70, 67)
    if len(text) <= single:
        return 1
    return -(-len(text) // multi)

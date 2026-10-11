"""A small rate-limit aware HTTP client for provider APIs (E22 §2).

* Retries ``429`` (honouring ``Retry-After``) and ``5xx`` with exponential backoff, a few
  times and briefly: long waits belong to the caller (Celery retry or the workflow's
  backoff), which gets ``RateLimited``.
* Maps ``401``/``403`` to ``AuthError``, ``404`` to ``NotFound`` and ``410`` to
  ``SyncTokenExpired`` (Google and Graph use it for stale sync tokens).
* Provider hosts are constants. URLs a tenant can influence (CalDAV servers) pass
  ``user_url=True`` and go through ``core.net.safe_urlopen`` (SSRF guard).

Never logs tokens or bodies.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import Message
from typing import Any

import structlog

from .base import AuthError, NotFound, ProviderError, RateLimited, Rejected, SyncTokenExpired

logger = structlog.get_logger(__name__)
RETRIES = 3
MAX_INLINE_WAIT = 5.0  # seconds we sleep in-process before handing back to the caller


@dataclass
class Response:
    status: int
    headers: Message
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body) if self.body else {}


def _open(request: urllib.request.Request, *, user_url: bool, timeout: float) -> Any:
    if user_url:
        from tutortrack.core.net import safe_urlopen

        return safe_urlopen(
            request.full_url,
            data=request.data,  # type: ignore[arg-type]
            headers=dict(request.header_items()),
            method=request.get_method(),
            timeout=timeout,
        )
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - provider constants


def request(
    method: str,
    url: str,
    *,
    token: str = "",
    auth_header: str = "",
    json_body: Any = None,
    form: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    user_url: bool = False,
    timeout: float = 15,
    retries: int = RETRIES,
    provider: str = "",
) -> Response:
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        url = f"{url}{'&' if '?' in url else '?'}{query}"
    sent_headers = {"Accept": "application/json", **(headers or {})}
    if token:
        sent_headers["Authorization"] = f"Bearer {token}"
    elif auth_header:
        sent_headers["Authorization"] = auth_header
    data = body
    if json_body is not None:
        data = json.dumps(json_body).encode()
        sent_headers.setdefault("Content-Type", "application/json")
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        sent_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    attempt = 0
    while True:
        attempt += 1
        req = urllib.request.Request(url, data=data, headers=sent_headers, method=method)  # noqa: S310
        try:
            with _open(req, user_url=user_url, timeout=timeout) as raw:
                return Response(raw.status, raw.headers, raw.read())
        except urllib.error.HTTPError as exc:
            status = exc.code
            payload = exc.read() if exc.fp else b""
            if status in (401, 403):
                raise AuthError(_message(payload, "The provider rejected our access.")) from exc
            if status == 404:
                raise NotFound(_message(payload, "Not found at the provider.")) from exc
            if status == 410:
                raise SyncTokenExpired("The sync token expired.") from exc
            if status == 429 or status >= 500:
                wait = _retry_after(exc.headers, attempt)
                logger.info("integrations.http_retry", provider=provider, status=status)
                if attempt <= retries and wait <= MAX_INLINE_WAIT:
                    time.sleep(wait)
                    continue
                if status == 429:
                    raise RateLimited("The provider is rate limiting us.", wait) from exc
                raise ProviderError(f"The provider had an error ({status}).") from exc
            if 300 <= status < 400:
                return Response(status, exc.headers, payload)
            if status in (400, 409, 422):
                raise Rejected(_message(payload, f"The provider refused ({status}).")) from exc
            raise ProviderError(_message(payload, f"The provider refused ({status}).")) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt <= retries:
                time.sleep(min(2 ** (attempt - 1) * 0.5, MAX_INLINE_WAIT))
                continue
            raise ProviderError("Couldn't reach the provider.") from exc


def _retry_after(headers: Any, attempt: int) -> float:
    value = headers.get("Retry-After") if headers is not None else None
    try:
        return max(float(value), 0) if value is not None else min(2 ** (attempt - 1), 30)
    except ValueError:
        return min(2 ** (attempt - 1), 30)


def _validation_messages(data: dict[str, Any]) -> str:
    """Xero ``Elements[].ValidationErrors[].Message`` and QuickBooks
    ``Fault.Error[].Detail``: the explanations users can act on."""
    found: list[str] = []
    for element in data.get("Elements") or []:
        for error in (element or {}).get("ValidationErrors") or []:
            found.append(str(error.get("Message", "")))
    fault = data.get("Fault")
    if isinstance(fault, dict):
        for error in fault.get("Error") or []:
            found.append(str(error.get("Detail") or error.get("Message") or ""))
    return "; ".join(m for m in found if m)


def _message(payload: bytes, default: str) -> str:
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return default
    if isinstance(data, dict):
        detailed = _validation_messages(data)
        if detailed:
            return detailed[:300]
        if isinstance(data.get("Message"), str) and "error" not in data:
            return str(data["Message"])[:300]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or default)[:300]
    if isinstance(error, str):
        return str(data.get("error_description") or error)[:300]
    return str(data.get("message") or default)[:300] if isinstance(data, dict) else default

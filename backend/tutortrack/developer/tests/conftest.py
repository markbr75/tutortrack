from __future__ import annotations

import io
import urllib.error
from collections.abc import Callable
from typing import Any

import pytest
from django.conf import settings
from django.db import transaction
from rest_framework.test import APIClient

from tutortrack.core.context import tenant_context
from tutortrack.developer import services

ROOT_HOST = settings.TENANT_BASE_DOMAIN  # the platform host: the token picks the tenant


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every hostname resolves to a public address (no network in tests); names containing
    "internal" resolve to a private one."""

    def resolve(host: str, port: int) -> tuple[str, ...]:
        return ("10.0.0.5",) if "internal" in host else ("93.184.216.34",)

    monkeypatch.setattr("tutortrack.core.net._resolve", resolve)


def make_key(org: Any, user: Any, scopes: list[str], **kwargs: Any) -> tuple[Any, str]:
    with tenant_context(org), transaction.atomic():
        return services.create_api_key(name="Integration", scopes_=scopes, user=user, **kwargs)


def bearer(token: str, host: str = ROOT_HOST, **extra: Any) -> APIClient:
    client = APIClient(HTTP_HOST=host, HTTP_AUTHORIZATION=f"Bearer {token}", **extra)
    return client


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"ok"):
        self.status = status
        self._body = body

    def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class Receiver:
    """Stands in for the customer's server: records requests, answers from a script."""

    def __init__(self, statuses: list[int] | None = None, default: int = 200):
        self.statuses = list(statuses or [])
        self.default = default
        self.requests: list[dict[str, Any]] = []

    def __call__(self, url: str, *, data: bytes | None = None, headers: Any = None,
                 method: str = "GET", timeout: float = 10) -> Any:  # fmt: skip
        self.requests.append({"url": url, "body": data or b"", "headers": dict(headers or {})})
        status = self.statuses.pop(0) if self.statuses else self.default
        if status >= 400:
            raise urllib.error.HTTPError(url, status, "error", {}, io.BytesIO(b"server error"))  # type: ignore[arg-type]
        return FakeResponse(status)


@pytest.fixture
def receiver(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Receiver]:
    def install(statuses: list[int] | None = None, default: int = 200) -> Receiver:
        fake = Receiver(statuses, default)
        monkeypatch.setattr("tutortrack.core.net.safe_urlopen", fake)
        return fake

    return install

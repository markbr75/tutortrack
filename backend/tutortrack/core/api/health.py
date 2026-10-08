"""Liveness (``/healthz``) and readiness (``/readyz``) probes for load balancers and ECS."""

from __future__ import annotations

from collections.abc import Callable

from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from ..redis import get_redis
from ..storage.client import bucket, s3_client


@require_GET
def healthz(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


def _check_database() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


def _check_redis() -> None:
    get_redis().ping()


def _check_storage() -> None:
    s3_client().head_bucket(Bucket=bucket())


CHECKS: dict[str, Callable[[], None]] = {
    "database": _check_database,
    "redis": _check_redis,
    "storage": _check_storage,
}


@require_GET
def readyz(request: HttpRequest) -> JsonResponse:
    results: dict[str, str] = {}
    for name, check in CHECKS.items():
        try:
            check()
            results[name] = "ok"
        except Exception as exc:
            results[name] = f"error: {type(exc).__name__}"
    healthy = all(v == "ok" for v in results.values())
    return JsonResponse(
        {"status": "ok" if healthy else "unavailable", "checks": results},
        status=200 if healthy else 503,
    )

"""Developer portal content (E27-T05): the public OpenAPI subset, a Postman collection
generated from it, and the API changelog. Guides (auth, pagination, errors, idempotency,
webhooks, rate limits, versioning) and code samples live in the admin app's docs page."""

from __future__ import annotations

import copy
import threading
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from django.utils.translation import gettext_lazy as _

HTTP_METHODS = ("get", "post", "put", "patch", "delete")

_lock = threading.Lock()
_cache: dict[str, Any] = {}


@dataclass(frozen=True)
class ChangelogEntry:
    released_on: date
    title: str
    change_kind: str  # added | changed | deprecated | removed | fixed
    description: str


CHANGELOG: tuple[ChangelogEntry, ...] = (
    ChangelogEntry(
        date(2026, 10, 10),
        str(_("Public API, API keys, OAuth apps and webhooks")),
        "added",
        str(
            _(
                "The v1 API is open to integrations: scoped API keys and OAuth2 apps, "
                "signed webhooks with retries and a delivery log, rate-limit headers."
            )
        ),
    ),
)


def changelog() -> list[dict[str, Any]]:
    return [asdict(e) for e in sorted(CHANGELOG, key=lambda e: e.released_on, reverse=True)]


def _full_schema() -> dict[str, Any]:
    from drf_spectacular.generators import SchemaGenerator

    schema: dict[str, Any] = SchemaGenerator().get_schema(request=None, public=True)
    return schema


def public_schema() -> dict[str, Any]:
    """The OpenAPI document restricted to operations marked ``x-visibility: public``,
    with components pruned to those still referenced. Cached per process."""
    with _lock:
        if "public" in _cache:
            return copy.deepcopy(_cache["public"])
    schema = _full_schema()
    paths: dict[str, Any] = {}
    for path, item in schema.get("paths", {}).items():
        ops = {
            method: op
            for method, op in item.items()
            if method in HTTP_METHODS and op.get("x-visibility") == "public"
        }
        if ops:
            paths[path] = ops
    schema["paths"] = paths
    schema["info"] = {
        **schema.get("info", {}),
        "title": "TutorTrack public API",
        "description": str(
            _(
                "Authenticate with `Authorization: Bearer <API key or OAuth access token>`. "
                "Cursor pagination, RFC 7807 errors, Idempotency-Key on POST, "
                "600 requests per minute per token."
            )
        ),
    }
    schema["components"] = _prune_components(schema.get("components", {}), paths)
    with _lock:
        _cache["public"] = schema
    return copy.deepcopy(schema)


def _refs(node: Any, found: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            _refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _refs(value, found)


def _prune_components(components: dict[str, Any], paths: dict[str, Any]) -> dict[str, Any]:
    schemas = components.get("schemas", {})
    wanted: set[str] = set()
    _refs(paths, wanted)
    pending = list(wanted)
    while pending:
        name = pending.pop()
        found: set[str] = set()
        _refs(schemas.get(name, {}), found)
        for extra in found - wanted:
            wanted.add(extra)
            pending.append(extra)
    out = dict(components)
    out["schemas"] = {k: v for k, v in schemas.items() if k in wanted}
    return out


def postman_collection(base_url: str = "{{baseUrl}}") -> dict[str, Any]:
    """A Postman v2.1 collection of the public operations, grouped by tag."""
    schema = public_schema()
    folders: dict[str, list[dict[str, Any]]] = {}
    for path, item in sorted(schema["paths"].items()):
        for method, op in item.items():
            tag = (op.get("tags") or ["api"])[0]
            raw_path = path.lstrip("/")
            segments = [
                f":{s[1:-1]}" if s.startswith("{") and s.endswith("}") else s
                for s in raw_path.split("/")
            ]
            request: dict[str, Any] = {
                "method": method.upper(),
                "header": [{"key": "Accept", "value": "application/json"}],
                "url": {
                    "raw": f"{base_url}/{'/'.join(segments)}",
                    "host": [base_url],
                    "path": segments,
                },
                "description": op.get("description", ""),
            }
            if method in ("post", "put", "patch"):
                request["header"].append({"key": "Content-Type", "value": "application/json"})
                request["body"] = {"mode": "raw", "raw": "{}"}
            folders.setdefault(tag, []).append(
                {"name": op.get("summary") or op.get("operationId", path), "request": request}
            )
    return {
        "info": {
            "name": "TutorTrack public API",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "auth": {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{apiToken}}", "type": "string"}],
        },
        "variable": [
            {"key": "baseUrl", "value": "https://app.tutortrack.app"},
            {"key": "apiToken", "value": ""},
        ],
        "item": [{"name": tag, "item": items} for tag, items in sorted(folders.items())],
    }


def clear_cache() -> None:
    with _lock:
        _cache.clear()

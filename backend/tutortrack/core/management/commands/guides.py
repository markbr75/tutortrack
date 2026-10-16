"""Keep the HTML guides in ``docs/guides/`` in step with the product (docs/guides/README.md).

``guides`` regenerates the reference blocks of ``api-guide.html`` (public endpoints from the
committed OpenAPI schema, token scopes and the webhook event catalogue) and then checks that
every navigation item of the admin app and portal has a guide section and that the root
README lists every backend app. ``guides --check`` writes nothing and fails on any drift.
"""

from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

ROOT = Path(settings.BASE_DIR).parent
GUIDES = ROOT / "docs" / "guides"
API_GUIDE = GUIDES / "api-guide.html"
OPENAPI = ROOT / "frontend" / "packages" / "api-client" / "openapi.json"
README = ROOT / "README.md"
BACKEND_APPS = ROOT / "backend" / "tutortrack"

# Navigation definitions → the app prefix used in ``data-route="<app>:<path>"``.
NAV_FILES = {
    "admin": (
        "frontend/apps/admin/src/layout/AppShell.tsx",
        "frontend/apps/admin/src/platform/PlatformShell.tsx",
    ),
    "portal": (
        "frontend/apps/portal/src/Shell.tsx",
        "frontend/apps/portal/src/tutor/TutorShell.tsx",
        "frontend/apps/portal/src/affiliate/AffiliatePages.tsx",
    ),
}
NAV_ITEM = re.compile(r"\{\s*to:\s*\"(/[^\"]*)\",\s*(?:key|label):")
DATA_ROUTE = re.compile(r"data-route=\"([^\"]+)\"")
BLOCK = re.compile(
    r"(<!-- BEGIN GENERATED: (?P<name>[a-z-]+) -->)\n.*?"
    r"(?=^[ \t]*<!-- END GENERATED: (?P=name) -->)",
    re.DOTALL | re.MULTILINE,
)
METHODS = ("get", "post", "put", "patch", "delete")
SPEC_REFS = re.compile(r"\s*\((?:FR|E\d|NFR|ADR)[^)]*\)")
# Docstrings that talk about our internals rather than what happened.
INTERNAL_NOTES = re.compile(r"\b(?:E\d\d|G\d|FR-\d+|ADR|workflow|handler|Temporal|outbox)\b", re.I)


def _e(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _sentence(text: str) -> str:
    """First sentence of a docstring, without spec references."""
    text = SPEC_REFS.sub("", " ".join(text.split()))
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    return match.group(1) if match else text


def _markup(text: str) -> str:
    """Escape ``text``, marking up ``code`` spans."""
    parts = re.split(r"``(.+?)``|`(.+?)`", text)
    return "".join(
        f"<code>{_e(part)}</code>" if i % 3 else _e(part)
        for i, part in enumerate(parts)
        if part is not None
    )


def _humanise(name: str) -> str:
    return name.replace("-", " ").replace("_", " ")


def _paginated(op: dict[str, Any]) -> bool:
    content = op.get("responses", {}).get("200", {}).get("content", {})
    schema = content.get("application/json", {}).get("schema", {})
    return schema.get("type") == "array" or "Paginated" in schema.get("$ref", "")


def _action(method: str, path: str, item: dict[str, Any]) -> str:
    """What an operation does, from its method and path shape (viewset docstrings are shared
    by every action, so they cannot tell list from create)."""
    segments = [s for s in path.split("/") if s][2:]  # drop "api", "v1"
    last = segments[-1]
    if last.startswith("{"):
        return {"get": "Get one", "put": "Replace", "patch": "Update"}.get(method, "Delete")
    if len(segments) == 1:
        verbs = {"get": "List", "post": "Create", "put": "Replace", "patch": "Update"}
        return verbs.get(method, "Delete")
    name = _humanise(last)
    if method == "get":
        return f"List {name}" if _paginated(item[method]) else f"Get {name}"
    if method == "post":
        return f"Add {name}" if "get" in item else name.capitalize()
    return f"Update {name}" if method in ("put", "patch") else f"Delete {name}"


def _title(tag: str) -> str:
    return tag.replace("-", " ").replace("_", " ").capitalize()


def endpoints_block() -> str:
    schema = json.loads(OPENAPI.read_text())
    by_tag: dict[str, list[tuple[str, str, dict[str, Any]]]] = defaultdict(list)
    for path, item in schema["paths"].items():
        for method in METHODS:
            op = item.get(method)
            if op and op.get("x-visibility") == "public":
                by_tag[(op.get("tags") or ["other"])[0]].append((method, path, item))
    total = sum(len(ops) for ops in by_tag.values())
    lines = [
        f'<p class="meta">{total} public operations in {len(by_tag)} groups, generated from '
        "<code>openapi.json</code>.</p>"
    ]
    for tag in sorted(by_tag):
        ops = by_tag[tag]
        sentences = [_sentence(item[m].get("summary") or item[m].get("description") or "")
                     for m, _p, item in ops]  # fmt: skip
        shared = [d for d in dict.fromkeys(sentences) if d and sentences.count(d) > 1]
        lines += [
            f'<details class="ref" id="ref-{_e(tag)}">',
            f'  <summary>{_e(_title(tag))} <span class="badge">{len(ops)}</span></summary>',
            *(f"  <p>{_markup(d)}</p>" for d in shared),
            '  <div class="table-wrap"><table class="endpoints">',
            '    <thead><tr><th scope="col">Method</th><th scope="col">Path</th>'
            '<th scope="col">Description</th><th scope="col">Scope</th></tr></thead>',
            "    <tbody>",
        ]
        for (method, path, item), sentence in zip(ops, sentences, strict=True):
            op = item[method]
            parts = [_e(_action(method, path, item))]
            if sentence and sentence not in shared:
                parts.append(f"— {_markup(sentence)}")
            headers = {p["name"] for p in op.get("parameters", []) if p.get("in") == "header"}
            parts += [f'<span class="badge">{h}</span>'
                      for h in ("Idempotency-Key", "If-Match") if h in headers]  # fmt: skip
            if op.get("deprecated"):
                parts.append('<span class="badge">Deprecated</span>')
            scopes = " ".join(f"<code>{_e(s)}</code>" for s in op.get("x-scopes", []))
            lines.append(
                f'      <tr><td><span class="method {method}">{method.upper()}</span></td>'
                f"<td><code>{_e(path)}</code></td><td>{' '.join(parts)}</td>"
                f'<td class="scopes">{scopes}</td></tr>'
            )
        lines += ["    </tbody>", "  </table></div>", "</details>"]
    return "\n".join(lines)


def scopes_block() -> str:
    from tutortrack.developer.scopes import RESOURCES

    lines = [
        '<div class="table-wrap"><table>',
        '  <thead><tr><th scope="col">Resource</th><th scope="col">Read scope</th>'
        '<th scope="col">Write scope</th></tr></thead>',
        "  <tbody>",
    ]
    for key, resource in RESOURCES.items():
        write = f"<code>{key}:write</code>" if resource.write else "—"
        lines.append(
            f"    <tr><td>{_e(resource.label)}</td><td><code>{key}:read</code></td>"
            f"<td>{write}</td></tr>"
        )
    lines += ["  </tbody>", "</table></div>"]
    return "\n".join(lines)


def events_block() -> str:
    from tutortrack.developer.catalogue import event_types

    by_aggregate: dict[str, list[Any]] = defaultdict(list)
    for event in event_types():
        by_aggregate[event.aggregate].append(event)
    total = sum(len(events) for events in by_aggregate.values())
    lines = [
        f'<p class="meta">{total} event types on {len(by_aggregate)} aggregates, generated from '
        "the webhook event catalogue.</p>"
    ]
    for aggregate in sorted(by_aggregate):
        events = by_aggregate[aggregate]
        lines += [
            f'<details class="ref" id="events-{_e(aggregate)}">',
            f'  <summary><code>{_e(aggregate)}.*</code> <span class="badge">{len(events)}</span>'
            "</summary>",
            '  <div class="table-wrap"><table>',
            '    <thead><tr><th scope="col">Event</th><th scope="col">Description</th>'
            '<th scope="col"><code>event_data</code> fields</th></tr></thead>',
            "    <tbody>",
        ]
        for event in events:
            fields = ", ".join(f"<code>{_e(n)}</code>" for n, _t in event.payload_fields) or "—"
            lines.append(
                f"      <tr><td><code>{_e(event.key)}</code></td>"
                f"<td>{_event_description(event)}</td><td>{fields}</td></tr>"
            )
        lines += ["    </tbody>", "  </table></div>", "</details>"]
    return "\n".join(lines)


def _event_description(event: Any) -> str:
    """The event's docstring when it is written for integrators, else one from its key."""
    sentence = _sentence(event.description)
    if sentence and not INTERNAL_NOTES.search(sentence):
        return _markup(sentence)
    aggregate, _sep, action = event.key.partition(".")
    return _e(f"{_humanise(aggregate).capitalize()} {_humanise(action)}.")


GENERATORS = {"endpoints": endpoints_block, "scopes": scopes_block, "webhook-events": events_block}


def render_api_guide(current: str) -> str:
    found: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        if name not in GENERATORS:
            raise CommandError(f"api-guide.html: unknown generated block {name!r}.")
        found.add(name)
        return f"{match.group(1)}\n{GENERATORS[name]()}\n"

    rendered = BLOCK.sub(replace, current)
    if missing := set(GENERATORS) - found:
        raise CommandError(f"api-guide.html: missing generated blocks {sorted(missing)}.")
    return rendered


def nav_routes() -> set[str]:
    routes = set()
    for app, files in NAV_FILES.items():
        for name in files:
            routes |= {f"{app}:{path}" for path in NAV_ITEM.findall((ROOT / name).read_text())}
    return routes


def documented_routes() -> set[str]:
    routes: set[str] = set()
    for page in GUIDES.glob("*.html"):
        for value in DATA_ROUTE.findall(page.read_text()):
            routes.update(value.split())
    return routes


class Command(BaseCommand):
    help = "Regenerate the API guide reference and check the guides and README are complete."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--check", action="store_true", help="Write nothing; fail if anything is stale."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        problems = []

        current = API_GUIDE.read_text()
        rendered = render_api_guide(current)
        if rendered != current:
            if options["check"]:
                problems.append("docs/guides/api-guide.html reference is stale: run `make docs`.")
            else:
                API_GUIDE.write_text(rendered)
                self.stdout.write("Updated docs/guides/api-guide.html.")

        problems += [
            f'Navigation item {route} has no guide section with data-route="{route}".'
            for route in sorted(nav_routes() - documented_routes())
        ]

        readme = README.read_text()
        problems += [
            f"README.md does not mention the backend app `{app.name}`."
            for app in sorted(BACKEND_APPS.iterdir())
            if (app / "apps.py").exists() and f"`{app.name}`" not in readme
        ]

        if problems:
            raise CommandError(
                "Guides are out of date (see docs/guides/README.md):\n  " + "\n  ".join(problems)
            )
        self.stdout.write(self.style.SUCCESS("Guides and README are up to date."))

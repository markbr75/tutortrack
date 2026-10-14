"""The guides generator and drift check (``manage.py guides``, docs/guides/README.md)."""

from __future__ import annotations

import pytest
from django.core.management.base import CommandError

from tutortrack.core.management.commands import guides

TEMPLATE = """<main>
  <!-- BEGIN GENERATED: scopes -->
  stale
  <!-- END GENERATED: scopes -->
  <!-- BEGIN GENERATED: webhook-events -->
  <!-- END GENERATED: webhook-events -->
  <!-- BEGIN GENERATED: endpoints -->
  <!-- END GENERATED: endpoints -->
</main>"""


def test_render_fills_every_block_from_schema_and_catalogues() -> None:
    rendered = guides.render_api_guide(TEMPLATE)

    assert "stale" not in rendered
    assert "<code>/api/v1/clients</code>" in rendered
    assert "<code>clients:read</code>" in rendered
    assert "<code>invoice.issued</code>" in rendered
    assert rendered.endswith("  <!-- END GENERATED: endpoints -->\n</main>")


def test_render_is_stable() -> None:
    once = guides.render_api_guide(TEMPLATE)

    assert guides.render_api_guide(once) == once


def test_only_public_operations_are_listed() -> None:
    rendered = guides.render_api_guide(TEMPLATE)

    assert "/api/v1/platform/" not in rendered
    assert "/api/v1/me" not in rendered


def test_missing_or_unknown_blocks_fail() -> None:
    with pytest.raises(CommandError, match="missing generated blocks"):
        guides.render_api_guide("<main></main>")
    with pytest.raises(CommandError, match="unknown generated block"):
        guides.render_api_guide(
            TEMPLATE + "<!-- BEGIN GENERATED: nope -->\n<!-- END GENERATED: nope -->"
        )


def test_navigation_items_are_read_from_every_shell() -> None:
    routes = guides.nav_routes()

    assert {"admin:/calendar", "admin:/platform/flags", "portal:/schedule"} <= routes
    assert {"portal:/tutor/earnings", "portal:/affiliate/payout"} <= routes


def test_endpoint_actions_come_from_method_and_path() -> None:
    collection: dict[str, dict[str, object]] = {"get": {}, "post": {}}
    detail: dict[str, dict[str, object]] = {"get": {}, "patch": {}, "delete": {}}

    assert guides._action("get", "/api/v1/clients", collection) == "List"
    assert guides._action("post", "/api/v1/clients", collection) == "Create"
    assert guides._action("get", "/api/v1/clients/{id}", detail) == "Get one"
    assert guides._action("delete", "/api/v1/clients/{id}", detail) == "Delete"
    assert guides._action("post", "/api/v1/clients/{id}/restore", {"post": {}}) == "Restore"
    assert guides._action("post", "/api/v1/clients/{id}/contacts", collection) == "Add contacts"

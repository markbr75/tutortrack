"""E16-T11: native app shells: the generic app and white-label configuration generated from
the E24 brand kit (management command and public endpoint)."""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command
from rest_framework.test import APIClient

from tutortrack.core import entitlements
from tutortrack.sites import mobile

from .factories import BrandKitFactory
from .test_branding_widgets import Entitlements

pytestmark = pytest.mark.django_db


@pytest.fixture
def plan(monkeypatch):
    def apply(*denied: str) -> None:
        monkeypatch.setattr(entitlements, "_resolver", Entitlements(*denied))

    apply()
    return apply


def test_app_ids_are_store_safe():
    assert mobile.app_id_for("bright-minds") == "app.tutortrack.tenant.bright_minds"
    assert mobile.app_id_for("123tutors") == "app.tutortrack.tenant.o123tutors"
    assert mobile.app_id_for("---") == "app.tutortrack.tenant.org"


def test_white_label_config_comes_from_the_brand_kit(org, plan):
    BrandKitFactory(organisation=org, primary_colour="#0f766e", app_name="Bright Minds App")
    config = mobile.app_config(org)
    assert config["white_label"] is True
    assert (config["appName"], config["primaryColour"]) == ("Bright Minds App", "#0f766e")
    assert config["serverUrl"] == f"{org.base_url}/portal/"
    assert config["allowNavigation"] == [config["serverUrl"].split("/")[2]]
    plan("white_label")
    generic = mobile.app_config(org)
    assert (generic["white_label"], generic["appId"]) == (False, mobile.GENERIC_APP_ID)
    assert generic["organisation"] == org.slug


def test_management_command_writes_the_configuration(org, plan, tmp_path):
    target = tmp_path / "white-label.json"
    call_command("mobile_app_config", "--org", org.slug, "--out", str(target))
    written = json.loads(target.read_text())
    assert written["appId"] == mobile.app_id_for(org.slug)
    out = StringIO()
    call_command("mobile_app_config", stdout=out)
    assert json.loads(out.getvalue())["appName"] == "TutorTrack"
    with pytest.raises(CommandError):
        call_command("mobile_app_config", "--org", "nobody")
    plan("white_label")
    with pytest.raises(CommandError):
        call_command("mobile_app_config", "--org", org.slug, "--require-white-label")


def test_public_endpoint_serves_the_configuration(org, plan):
    client = APIClient(HTTP_HOST=f"{org.slug}.{settings.TENANT_BASE_DOMAIN}")
    response = client.get("/api/v1/public/mobile-app")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["white_label"] is True
    assert body["serverUrl"].endswith("/portal/")

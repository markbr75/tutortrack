from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _
from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer
from tutortrack.core.models import StoredFile
from tutortrack.core.time import is_valid_timezone

from ..models import Branch, Organisation

ADDRESS_KEYS = ("line1", "line2", "city", "region", "postcode", "country")


def validate_address(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) - set(ADDRESS_KEYS):
        raise serializers.ValidationError(
            _("Address fields: %(keys)s.") % {"keys": ", ".join(ADDRESS_KEYS)}
        )
    return {k: str(v).strip()[:200] for k, v in value.items() if v is not None}


def validate_tz(value: str) -> str:
    if not is_valid_timezone(value):
        raise serializers.ValidationError(_("Unknown timezone."))
    return value


class TenantFileField(serializers.PrimaryKeyRelatedField):
    """A StoredFile of the organisation in context (evaluated per request)."""

    def get_queryset(self) -> Any:
        return StoredFile.objects.all()


class OrganisationSerializer(BaseModelSerializer):
    logo = TenantFileField(allow_null=True, required=False)
    url = serializers.CharField(source="base_url", read_only=True)
    address = serializers.JSONField(required=False)
    timezone = serializers.CharField(required=False)
    primary_colour = serializers.RegexField(
        r"^(#[0-9a-fA-F]{6})?$", required=False, allow_blank=True
    )

    class Meta:
        model = Organisation
        fields = [
            "id", "name", "legal_name", "slug", "url", "business_type", "mode", "status",
            "country", "region", "default_currency", "timezone", "locale", "logo",
            "primary_colour", "contact_email", "contact_phone", "address", "company_number",
            "vat_number", "tax_number", "fiscal_year_start_month", "week_start_day",
            "date_format", "time_format", "has_demo_data", "created_at",
        ]  # fmt: skip
        read_only_fields = ["id", "status", "region", "has_demo_data", "created_at"]
        # Tax ids are encrypted at rest and only shown to people who manage the profile.
        field_permissions = {"tax_number": "org.settings.manage"}

    def validate_address(self, value: Any) -> dict[str, str]:
        return validate_address(value)

    def validate_timezone(self, value: str) -> str:
        return validate_tz(value)


class BranchSerializer(BaseModelSerializer):
    address = serializers.JSONField(required=False)
    timezone = serializers.CharField(required=False)

    class Meta:
        model = Branch
        fields = [
            "id", "name", "code", "address", "timezone", "currency", "locale",
            "tax_settings", "branding", "email_sender_name", "email_sender_address",
            "invoice_prefix", "is_default", "archived_at", "created_at",
        ]  # fmt: skip
        read_only_fields = ["id", "is_default", "archived_at", "created_at"]
        extra_kwargs = {
            "currency": {"required": False},
            "locale": {"required": False},
        }

    def validate_address(self, value: Any) -> dict[str, str]:
        return validate_address(value)

    def validate_timezone(self, value: str) -> str:
        return validate_tz(value)


class SettingDescriptionSerializer(serializers.Serializer):
    """One registered setting. Fields are declared in get_fields() because names such as
    ``label`` and ``help_text`` clash with attributes of DRF's Field class."""

    def get_fields(self) -> dict[str, serializers.Field]:
        return {
            "key": serializers.CharField(),
            "type": serializers.ChoiceField(choices=["int", "str", "bool", "choice", "object"]),
            "scope": serializers.ChoiceField(choices=["organisation", "branch"]),
            "default": serializers.JSONField(),
            "label": serializers.CharField(),
            "help_text": serializers.CharField(),
            "choices": serializers.ListField(child=serializers.DictField(), required=False),
            "min_value": serializers.IntegerField(required=False),
            "max_value": serializers.IntegerField(required=False),
            "max_length": serializers.IntegerField(required=False),
            "schema": serializers.DictField(required=False),
        }


class SettingsAreaSerializer(serializers.Serializer):
    area = serializers.CharField()
    branch = serializers.UUIDField(allow_null=True)
    values = serializers.DictField(child=serializers.JSONField())
    overrides = serializers.ListField(
        child=serializers.CharField(),
        help_text="Keys overridden at branch level (empty without ?branch=).",
    )
    schema = SettingDescriptionSerializer(many=True)


class SettingsPatchSerializer(serializers.Serializer):
    values = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        help_text="{key: value}. null resets the key (org) or removes the override (branch).",
    )

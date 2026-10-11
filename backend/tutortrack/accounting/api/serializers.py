from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer

from .. import mappings, selectors
from ..models import AccountingConnection, ExternalRecordLink, SyncLogEntry
from ..org_settings import EXPORT_FORMATS


class AccountingStatsSerializer(serializers.Serializer):
    pending = serializers.IntegerField()
    synced = serializers.IntegerField()
    error = serializers.IntegerField()
    skipped = serializers.IntegerField()


class MappingProblemSerializer(serializers.Serializer):
    kind = serializers.CharField()
    key = serializers.CharField(allow_blank=True)
    message = serializers.CharField()


class BackfillProgressSerializer(serializers.Serializer):
    status = serializers.CharField(required=False)
    since = serializers.DateField(required=False)
    synced = serializers.IntegerField(required=False)
    failed = serializers.IntegerField(required=False, source="errors")
    skipped = serializers.IntegerField(required=False)
    started_at = serializers.DateTimeField(required=False)
    finished_at = serializers.DateTimeField(required=False)


class AccountingConnectionSerializer(BaseModelSerializer):
    """A ledger connection with its sync options, health and dashboard counts."""

    provider_name = serializers.SerializerMethodField()
    status = serializers.CharField(source="connection.status", read_only=True)
    account_name = serializers.CharField(source="connection.account_name", read_only=True)
    connection_error = serializers.CharField(source="connection.error", read_only=True)
    last_sync_at = serializers.DateTimeField(
        source="connection.last_sync_at", read_only=True, allow_null=True
    )
    simulated = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()
    problems = serializers.SerializerMethodField()
    backfill_progress = serializers.SerializerMethodField()

    class Meta:
        model = AccountingConnection
        fields = [
            "id",
            "connection",
            "provider",
            "provider_name",
            "status",
            "account_name",
            "connection_error",
            "company_name",
            "base_currency",
            "lock_date",
            "enabled",
            "enabled_at",
            "mode",
            "start_date",
            "sync_bills",
            "attach_pdf",
            "lock_behaviour",
            "chart_fetched_at",
            "last_sync_at",
            "simulated",
            "stats",
            "problems",
            "backfill_progress",
            "created_at",
        ]
        read_only_fields = [
            f
            for f in fields
            if f not in ("mode", "start_date", "sync_bills", "attach_pdf", "lock_behaviour")
        ]

    @extend_schema_field(serializers.CharField())
    def get_provider_name(self, obj: AccountingConnection) -> str:
        from ..errors import LABELS

        return LABELS.get(obj.provider, obj.provider)

    @extend_schema_field(serializers.BooleanField())
    def get_simulated(self, obj: AccountingConnection) -> bool:
        from tutortrack.integrations import providers

        return providers.is_fake(obj.provider)

    @extend_schema_field(AccountingStatsSerializer)
    def get_stats(self, obj: AccountingConnection) -> dict[str, int]:
        return selectors.stats(obj)

    @extend_schema_field(MappingProblemSerializer(many=True))
    def get_problems(self, obj: AccountingConnection) -> list[dict[str, str]]:
        return mappings.problems(obj.provider, obj)

    @extend_schema_field(BackfillProgressSerializer)
    def get_backfill_progress(self, obj: AccountingConnection) -> dict[str, Any]:
        keep = ("status", "since", "synced", "errors", "skipped", "started_at", "finished_at")
        data = {k: v for k, v in (obj.backfill or {}).items() if k in keep}
        return dict(BackfillProgressSerializer(data).data)


class AdoptConnectionSerializer(serializers.Serializer):
    connection = serializers.UUIDField(help_text="The integration connection (Xero/QuickBooks).")


class EnableSerializer(serializers.Serializer):
    backfill_from = serializers.DateField(
        required=False, allow_null=True, help_text="Also sync history from this date."
    )


class BackfillSerializer(serializers.Serializer):
    since = serializers.DateField()


class ChartAccountSerializer(serializers.Serializer):
    id = serializers.CharField()
    code = serializers.CharField(allow_blank=True)
    name = serializers.CharField()
    type = serializers.CharField()
    active = serializers.BooleanField()


class ChartTaxCodeSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    rate = serializers.CharField(allow_blank=True)
    active = serializers.BooleanField()


class ChartTrackingSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    options = serializers.ListField(child=serializers.ListField(child=serializers.CharField()))


class ChartSerializer(serializers.Serializer):
    accounts = ChartAccountSerializer(many=True)
    tax_codes = ChartTaxCodeSerializer(many=True)
    tracking = ChartTrackingSerializer(many=True)


class AccountMappingRowSerializer(serializers.Serializer):
    kind = serializers.CharField()
    key = serializers.CharField(default="default", max_length=80)
    external_id = serializers.CharField(allow_blank=True, max_length=100)
    code = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class TaxMappingRowSerializer(serializers.Serializer):
    tax_rate = serializers.UUIDField(allow_null=True, required=False)
    external_id = serializers.CharField(allow_blank=True, max_length=100)
    name = serializers.CharField(required=False, allow_blank=True, max_length=200)


class TrackingMappingRowSerializer(serializers.Serializer):
    branch = serializers.UUIDField()
    category_id = serializers.CharField(allow_blank=True, max_length=100)
    option_id = serializers.CharField(allow_blank=True, max_length=100)
    name = serializers.CharField(required=False, allow_blank=True, max_length=200)


class MappingKindSerializer(serializers.Serializer):
    kind = serializers.CharField()
    name = serializers.CharField()
    is_required = serializers.BooleanField()


class MappingKeySerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()


class MappingSetSerializer(serializers.Serializer):
    """A mapping set: accounts per kind and key, tax codes per tax rate, tracking per
    branch; plus what is still missing and the keys that can be mapped."""

    provider = serializers.CharField(read_only=True)
    accounts = AccountMappingRowSerializer(many=True)
    taxes = TaxMappingRowSerializer(many=True)
    tracking = TrackingMappingRowSerializer(many=True)
    kinds = MappingKindSerializer(many=True, read_only=True)
    revenue_keys = MappingKeySerializer(many=True, read_only=True)
    clearing_keys = MappingKeySerializer(many=True, read_only=True)
    expense_keys = MappingKeySerializer(many=True, read_only=True)
    tax_rates = MappingKeySerializer(many=True, read_only=True)
    branches = MappingKeySerializer(many=True, read_only=True)
    problems = MappingProblemSerializer(many=True, read_only=True)


class SyncLogEntrySerializer(BaseModelSerializer):
    class Meta:
        model = SyncLogEntry
        fields = ["id", "outcome", "message", "created_at"]
        read_only_fields = fields


class ExternalRecordLinkSerializer(BaseModelSerializer):
    """One record's sync status in the ledger."""

    class Meta:
        model = ExternalRecordLink
        fields = [
            "id",
            "connection",
            "provider",
            "object_type",
            "object_id",
            "label",
            "external_id",
            "external_number",
            "status",
            "error",
            "error_code",
            "attempts",
            "last_attempt_at",
            "synced_at",
            "posted_date",
            "updated_at",
        ]
        read_only_fields = fields


class ExternalRecordDetailSerializer(ExternalRecordLinkSerializer):
    log = serializers.SerializerMethodField()

    class Meta(ExternalRecordLinkSerializer.Meta):
        fields = [*ExternalRecordLinkSerializer.Meta.fields, "log"]
        read_only_fields = fields

    @extend_schema_field(SyncLogEntrySerializer(many=True))
    def get_log(self, obj: ExternalRecordLink) -> list[dict[str, Any]]:
        return list(SyncLogEntrySerializer(selectors.log(obj), many=True).data)


class SkipSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=300)


class RetryResultSerializer(serializers.Serializer):
    retried = serializers.IntegerField()


class ExportQuerySerializer(serializers.Serializer):
    file_format = serializers.ChoiceField(choices=EXPORT_FORMATS, default="generic")
    start = serializers.DateField()
    end = serializers.DateField()
    mapping_set = serializers.ChoiceField(
        choices=[("export", "export"), ("xero", "xero"), ("quickbooks", "quickbooks")],
        default="export",
    )

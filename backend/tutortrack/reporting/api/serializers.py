from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..models import ReportRun, SavedReport, ScheduledReport

# --- reports ------------------------------------------------------------------------------------


class OptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]


class ReportDefinitionSerializer(serializers.Serializer):
    key = serializers.CharField()
    title = serializers.CharField()
    category = serializers.CharField()
    category_label = serializers.CharField()
    description = serializers.CharField()
    filters = serializers.ListField(child=serializers.CharField())
    group_by = OptionSerializer(many=True)
    period = serializers.BooleanField()
    default_period = serializers.CharField()


class ReportColumnSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    type = serializers.ChoiceField(
        choices=["text", "number", "count", "money", "hours", "percent", "date"]
    )


class ReportChartSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["bar", "line", "pie"])
    x = serializers.CharField()
    y = serializers.ListField(child=serializers.CharField())
    stacked = serializers.BooleanField(default=False)


class ReportResultSerializer(serializers.Serializer):
    report = ReportDefinitionSerializer()
    params = serializers.DictField(child=serializers.CharField())
    period = serializers.DictField(child=serializers.CharField(), allow_null=True)
    columns = ReportColumnSerializer(many=True)
    rows = serializers.ListField(child=serializers.DictField())
    totals = serializers.ListField(child=serializers.DictField())
    chart = ReportChartSerializer(allow_null=True)
    notes = serializers.ListField(child=serializers.CharField())
    generated_at = serializers.DateTimeField()


# --- dashboards ---------------------------------------------------------------------------------


class LayoutItemSerializer(serializers.Serializer):
    widget = serializers.CharField(max_length=40)
    size = serializers.ChoiceField(choices=["s", "m", "l"], default="s")


class DashboardLayoutSerializer(serializers.Serializer):
    preset = serializers.CharField(read_only=True)
    customised = serializers.BooleanField(read_only=True)
    widgets = LayoutItemSerializer(many=True)


class WidgetInfoSerializer(serializers.Serializer):
    key = serializers.CharField()
    title = serializers.CharField()
    category = serializers.CharField()
    kind = serializers.ChoiceField(choices=["kpi", "chart", "list"])
    default_size = serializers.CharField()
    report = serializers.CharField(allow_blank=True)


class WidgetValueSerializer(serializers.Serializer):
    label = serializers.CharField(allow_blank=True)  # type: ignore[assignment]
    currency = serializers.CharField(allow_blank=True)
    value = serializers.CharField()
    previous = serializers.CharField(allow_null=True)


class WidgetPointSerializer(serializers.Serializer):
    x = serializers.CharField()
    currency = serializers.CharField(allow_blank=True)
    y = serializers.DictField(child=serializers.CharField())


class WidgetRowSerializer(serializers.Serializer):
    label = serializers.CharField(allow_blank=True)  # type: ignore[assignment]
    value = serializers.CharField(allow_blank=True)
    detail = serializers.CharField(allow_blank=True)


class WidgetDataSerializer(serializers.Serializer):
    widget = WidgetInfoSerializer()
    unit = serializers.ChoiceField(choices=["count", "money", "percent", "hours"])
    period = serializers.DictField(child=serializers.CharField())
    previous_period = serializers.DictField(child=serializers.CharField(), allow_null=True)
    values = WidgetValueSerializer(many=True)
    series = WidgetPointSerializer(many=True)
    rows = WidgetRowSerializer(many=True)
    report_params = serializers.DictField(child=serializers.CharField())


# --- saved and scheduled reports ----------------------------------------------------------------


class SavedReportSerializer(serializers.ModelSerializer):
    owner_name = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()
    params = serializers.DictField(child=serializers.CharField(allow_blank=True), required=False)

    class Meta:
        model = SavedReport
        fields = [
            "id",
            "name",
            "report_key",
            "params",
            "shared",
            "owner_name",
            "is_mine",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "owner_name", "is_mine", "created_at", "updated_at"]

    @extend_schema_field(serializers.CharField())
    def get_owner_name(self, obj: SavedReport) -> str:
        return str(obj.owner.get_full_name() or obj.owner.email)

    @extend_schema_field(serializers.BooleanField())
    def get_is_mine(self, obj: SavedReport) -> bool:
        request = self.context.get("request")
        return bool(request and obj.owner_id == request.user.pk)


class SavedReportUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    params = serializers.DictField(child=serializers.CharField(allow_blank=True), required=False)
    shared = serializers.BooleanField(required=False)


class RecipientSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    email = serializers.EmailField()


class ScheduledReportSerializer(serializers.ModelSerializer):
    saved_report = serializers.PrimaryKeyRelatedField(queryset=SavedReport.objects.none())
    saved_report_name = serializers.CharField(source="saved_report.name", read_only=True)
    report_key = serializers.CharField(source="saved_report.report_key", read_only=True)
    recipients = serializers.ListField(child=serializers.UUIDField(), write_only=True)
    recipient_details = serializers.SerializerMethodField()
    time = serializers.TimeField(format="%H:%M")

    class Meta:
        model = ScheduledReport
        fields = [
            "id",
            "saved_report",
            "saved_report_name",
            "report_key",
            "frequency",
            "weekday",
            "day_of_month",
            "time",
            "format",
            "recipients",
            "recipient_details",
            "enabled",
            "last_run_at",
            "created_at",
        ]
        read_only_fields = ["id", "last_run_at", "created_at"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and getattr(request, "organisation", None) is not None:
            from ..selectors import saved_reports

            field: Any = self.fields["saved_report"]
            field.queryset = saved_reports(request.user)

    @extend_schema_field(RecipientSerializer(many=True))
    def get_recipient_details(self, obj: ScheduledReport) -> list[dict[str, Any]]:
        return [
            {"id": u.pk, "name": u.get_full_name() or u.email, "email": u.email}
            for u in obj.recipients.all()
        ]


class ScheduledReportUpdateSerializer(serializers.Serializer):
    frequency = serializers.ChoiceField(choices=ScheduledReport.Frequency.choices, required=False)
    weekday = serializers.IntegerField(min_value=0, max_value=6, required=False)
    day_of_month = serializers.IntegerField(min_value=1, max_value=28, required=False)
    time = serializers.TimeField(required=False)
    format = serializers.ChoiceField(choices=ScheduledReport.Format.choices, required=False)
    recipients = serializers.ListField(child=serializers.UUIDField(), required=False)
    enabled = serializers.BooleanField(required=False)


class ReportRunSerializer(serializers.ModelSerializer):
    file_name = serializers.SerializerMethodField()
    saved_report_name = serializers.SerializerMethodField()

    class Meta:
        model = ReportRun
        fields = [
            "id",
            "report_key",
            "format",
            "status",
            "row_count",
            "recipients",
            "error",
            "file_name",
            "saved_report_name",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_file_name(self, obj: ReportRun) -> str | None:
        return obj.file.filename if obj.file_id and obj.file else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_saved_report_name(self, obj: ReportRun) -> str | None:
        scheduled = obj.scheduled_report
        return scheduled.saved_report.name if scheduled is not None else None


class ReportDownloadSerializer(serializers.Serializer):
    url = serializers.URLField()
    expires_in = serializers.IntegerField()


class RebuildSerializer(serializers.Serializer):
    lessons = serializers.IntegerField()
    charges = serializers.IntegerField()
    payments = serializers.IntegerField()
    pay_items = serializers.IntegerField()


class StaffMemberSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    email = serializers.EmailField()

from typing import Any

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest

from tutortrack.core.exceptions import DomainError

from . import lifecycle
from .models import Organisation, OrganisationDomain, ReservedSlug


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    """Platform operators only. E30 replaces this with the platform console."""

    list_display = ("name", "slug", "status", "business_type", "country", "created_at")
    search_fields = ("name", "slug", "contact_email")
    list_filter = ("status", "business_type", "region")
    readonly_fields = ("status", "suspended_at", "suspension_reason", "closed_at", "created_by")
    actions = ["suspend", "reactivate", "reopen"]

    @admin.action(description="Suspend (read-only for owners/admins)")
    def suspend(self, request: HttpRequest, queryset: QuerySet[Organisation]) -> None:
        self._run(
            request,
            queryset,
            lambda org: lifecycle.suspend_organisation(
                org, reason=f"Suspended by platform staff ({request.user})"
            ),
        )

    @admin.action(description="Reactivate")
    def reactivate(self, request: HttpRequest, queryset: QuerySet[Organisation]) -> None:
        self._run(request, queryset, lifecycle.reactivate_organisation)

    @admin.action(description="Reopen a closed account (during the grace period)")
    def reopen(self, request: HttpRequest, queryset: QuerySet[Organisation]) -> None:
        for org in queryset:
            try:
                if not lifecycle.request_reopen(org):
                    self.message_user(request, f"{org}: closure already finished", messages.ERROR)
            except DomainError as exc:
                self.message_user(request, f"{org}: {exc.detail}", messages.ERROR)

    def _run(self, request: HttpRequest, queryset: QuerySet[Organisation], action: Any) -> None:
        for org in queryset:
            try:
                action(org)
            except DomainError as exc:
                self.message_user(request, f"{org}: {exc.detail}", messages.ERROR)


@admin.register(OrganisationDomain)
class OrganisationDomainAdmin(admin.ModelAdmin):
    list_display = ("hostname", "organisation", "type", "verified_at", "redirect_until")
    search_fields = ("hostname",)
    list_filter = ("type",)


@admin.register(ReservedSlug)
class ReservedSlugAdmin(admin.ModelAdmin):
    list_display = ("slug", "reason")
    search_fields = ("slug",)

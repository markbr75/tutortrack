"""Abstract base models every TutorTrack model builds on.

* ``UUIDModel``: UUIDv7 primary key.
* ``TimeStampedModel``: ``created_at`` / ``updated_at``.
* ``TenantModel``: owned by an Organisation; the default manager is scoped to the
  organisation in context and **raises** ``NoTenantContext`` when there is none.
* ``ArchivableModel``: soft archive (``archived_at``) for people-like records.

Branch scoping (``BranchScopedModel``) is added in E02 once Branch exists.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.conf import settings
from django.db import models
from django.utils import timezone

from ..context import current_organisation_id, get_request_context, require_organisation_id
from ..exceptions import CrossTenantWrite
from ..ids import new_id


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=new_id, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# --- tenancy ------------------------------------------------------------------------------------


class TenantQuerySet(models.QuerySet):
    pass


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):  # type: ignore[misc]
    """Default manager for tenant data: always filtered to the organisation in context."""

    def get_queryset(self) -> TenantQuerySet:
        return super().get_queryset().filter(organisation_id=require_organisation_id())


class UnscopedManager(models.Manager.from_queryset(TenantQuerySet)):  # type: ignore[misc]
    """Explicitly unscoped access (platform admin, migrations, cross-tenant jobs) only."""


class TenantModel(UUIDModel, TimeStampedModel):
    organisation = models.ForeignKey(
        "tenancy.Organisation", on_delete=models.CASCADE, related_name="+", editable=False
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
    )

    objects: ClassVar[TenantManager] = TenantManager()
    all_tenants: ClassVar[UnscopedManager] = UnscopedManager()

    # Field names whose values must never appear in audit diffs or logs.
    audit_sensitive_fields: ClassVar[frozenset[str]] = frozenset()

    class Meta:
        abstract = True
        base_manager_name = "all_tenants"

    def save(self, *args: Any, **kwargs: Any) -> None:
        context_org = current_organisation_id()
        if self.organisation_id is None:
            self.organisation_id = require_organisation_id()
        elif context_org is not None and self.organisation_id != context_org:
            raise CrossTenantWrite()

        user_id = get_request_context().user_id
        if user_id is not None:
            if self._state.adding and self.created_by_id is None:
                self.created_by_id = user_id
            self.updated_by_id = user_id
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "updated_by", "updated_at"}
        super().save(*args, **kwargs)


# --- archiving ----------------------------------------------------------------------------------


class ArchivableQuerySet(TenantQuerySet):
    def active(self) -> ArchivableQuerySet:
        return self.filter(archived_at__isnull=True)

    def archived(self) -> ArchivableQuerySet:
        return self.filter(archived_at__isnull=False)


class ArchivableTenantManager(TenantManager.from_queryset(ArchivableQuerySet)):  # type: ignore[misc]
    pass


class ArchivableModel(TenantModel):
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects: ClassVar[ArchivableTenantManager] = ArchivableTenantManager()
    all_tenants: ClassVar[UnscopedManager] = UnscopedManager()

    class Meta(TenantModel.Meta):
        abstract = True

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def archive(self) -> None:
        if self.archived_at is None:
            self.archived_at = timezone.now()
            self.save(update_fields=["archived_at", "updated_at"])

    def unarchive(self) -> None:
        if self.archived_at is not None:
            self.archived_at = None
            self.save(update_fields=["archived_at", "updated_at"])

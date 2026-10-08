from __future__ import annotations

from typing import Any

from django.db import models
from rest_framework.permissions import IsAuthenticated

from ..permissions import HasOrganisation


class TenantScopedViewMixin:
    """Base for views over tenant data.

    Subclasses set ``model`` and implement ``get_tenant_queryset()``. During OpenAPI
    generation there is no request tenant, so an empty unscoped queryset is returned
    instead (it is never evaluated).
    """

    model: type[models.Model]
    permission_classes: Any = [IsAuthenticated, HasOrganisation]

    def get_queryset(self) -> models.QuerySet[Any]:
        if getattr(self, "swagger_fake_view", False):
            manager = getattr(self.model, "all_tenants", self.model._default_manager)
            return manager.none()
        return self.get_tenant_queryset()

    def get_tenant_queryset(self) -> models.QuerySet[Any]:
        raise NotImplementedError

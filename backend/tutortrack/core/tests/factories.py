from typing import Any

import factory

from tutortrack.core.context import tenant_context

from .testapp.models import Gadget, Gizmo, Widget


class TenantFactory(factory.django.DjangoModelFactory):
    """Base for tenant-owned models. Creates through ``all_tenants`` inside the object's own
    tenant context (so the RLS policies accept the insert), whether or not the test is in a
    tenant context; pass ``organisation=`` to choose the tenant."""

    class Meta:
        abstract = True

    organisation = factory.SubFactory("tutortrack.tenancy.tests.factories.OrganisationFactory")

    @classmethod
    def _get_manager(cls, model_class: Any) -> Any:
        return model_class.all_tenants

    @classmethod
    def _create(cls, model_class: Any, *args: Any, **kwargs: Any) -> Any:
        organisation = kwargs.get("organisation")
        org_id = kwargs.get("organisation_id") or getattr(organisation, "pk", None)
        with tenant_context(org_id):
            return super()._create(model_class, *args, **kwargs)


class GadgetFactory(TenantFactory):
    class Meta:
        model = Gadget

    name = factory.Sequence(lambda n: f"Gadget {n}")


class WidgetFactory(TenantFactory):
    class Meta:
        model = Widget

    name = factory.Sequence(lambda n: f"Widget {n}")


class GizmoFactory(TenantFactory):
    """Branch defaults to the organisation's default branch when not given."""

    class Meta:
        model = Gizmo

    name = factory.Sequence(lambda n: f"Gizmo {n}")

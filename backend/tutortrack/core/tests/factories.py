from typing import Any

import factory

from tutortrack.tenancy.tests.factories import OrganisationFactory

from .testapp.models import Gadget, Widget


class TenantFactory(factory.django.DjangoModelFactory):
    """Base for tenant-owned models. Creates through ``all_tenants`` so factories work with
    or without a tenant context; pass ``organisation=`` to choose the tenant."""

    class Meta:
        abstract = True

    organisation = factory.SubFactory(OrganisationFactory)

    @classmethod
    def _get_manager(cls, model_class: Any) -> Any:
        return model_class.all_tenants


class GadgetFactory(TenantFactory):
    class Meta:
        model = Gadget

    name = factory.Sequence(lambda n: f"Gadget {n}")


class WidgetFactory(TenantFactory):
    class Meta:
        model = Widget

    name = factory.Sequence(lambda n: f"Widget {n}")

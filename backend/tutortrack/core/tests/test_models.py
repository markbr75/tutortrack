import pytest

from tutortrack.core.context import request_context, tenant_context
from tutortrack.core.exceptions import CrossTenantWrite, NoTenantContext
from tutortrack.core.ids import new_id

from .factories import GadgetFactory, WidgetFactory
from .testapp.models import Gadget, Widget

pytestmark = pytest.mark.django_db


def test_uuid7_ids_are_time_ordered():
    ids = [new_id() for _ in range(50)]
    assert ids == sorted(ids)
    assert all(i.version == 7 for i in ids)


def test_querying_tenant_model_without_context_raises(org):
    GadgetFactory(organisation=org)
    with pytest.raises(NoTenantContext):
        list(Gadget.objects.all())


def test_queries_are_scoped_to_the_organisation_in_context(org, other_org):
    mine = GadgetFactory(organisation=org)
    theirs = GadgetFactory(organisation=other_org)

    with tenant_context(org):
        assert list(Gadget.objects.all()) == [mine]
        assert not Gadget.objects.filter(pk=theirs.pk).exists()
    with tenant_context(other_org):
        assert list(Gadget.objects.all()) == [theirs]


def test_all_tenants_manager_is_unscoped(org, other_org):
    GadgetFactory(organisation=org)
    GadgetFactory(organisation=other_org)
    assert Gadget.all_tenants.count() == 2


def test_save_assigns_organisation_from_context(tenant):
    gadget = Gadget.objects.create(name="Projector")
    assert gadget.organisation_id == tenant.pk


def test_save_without_context_or_organisation_raises(db):
    with pytest.raises(NoTenantContext):
        Gadget(name="Orphan").save()


def test_cannot_save_another_organisations_object_in_context(org, other_org):
    theirs = GadgetFactory(organisation=other_org)
    with tenant_context(org):
        theirs.name = "Hijacked"
        with pytest.raises(CrossTenantWrite):
            theirs.save()


def test_created_by_and_updated_by_come_from_request_context(tenant, user, superuser):
    with request_context(user_id=user.pk):
        gadget = Gadget.objects.create(name="Laptop")
    assert gadget.created_by_id == user.pk
    assert gadget.updated_by_id == user.pk

    with request_context(user_id=superuser.pk):
        gadget.name = "Laptop 2"
        gadget.save(update_fields=["name"])
    gadget.refresh_from_db()
    assert gadget.created_by_id == user.pk
    assert gadget.updated_by_id == superuser.pk


def test_archive_and_active_queryset(tenant):
    keep = WidgetFactory(organisation=tenant)
    gone = WidgetFactory(organisation=tenant)
    gone.archive()

    assert gone.is_archived
    assert list(Widget.objects.active()) == [keep]
    assert list(Widget.objects.archived()) == [gone]

    gone.unarchive()
    assert Widget.objects.active().count() == 2


def test_reverse_relations_use_the_scoped_manager(org, other_org):
    gadget = GadgetFactory(organisation=org)
    WidgetFactory(organisation=org, gadget=gadget)
    with tenant_context(org):
        assert gadget.widget_set.count() == 1

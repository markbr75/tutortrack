"""Gap batch G2 (FR-02-6, FR-27-6): the apps' in-product sample data.

A fresh organisation gets a small, coherent dataset (families, tutors, services, weekly
lessons at fixed local times, reports, invoices in several states, payments, enquiries, a
class, homework, a goal and a review); "Clear demo data" removes every row it added and
nothing else."""

from __future__ import annotations

from collections import Counter

import pytest
from django.apps import apps

from tutortrack.core.context import tenant_context
from tutortrack.core.models import TenantModel
from tutortrack.identity.models import Membership
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.tenancy import demo
from tutortrack.tenancy.models import DemoRecord

pytestmark = pytest.mark.django_db

# Rows that are history, not data: kept on purpose.
NOT_WIPED = {"core.sequence"}


def tenant_counts() -> Counter[str]:
    counts: Counter[str] = Counter()
    for model in apps.get_models():
        if issubclass(model, TenantModel) and model is not DemoRecord:
            counts[model._meta.label_lower] = model._default_manager.count()
    return counts


def test_fresh_organisation_gets_coherent_sample_data_and_clearing_removes_it_all(org):
    from tutortrack.billing.models import Invoice
    from tutortrack.catalogue.models import Service
    from tutortrack.core.context import branch_scope
    from tutortrack.core.models import OutboxEvent
    from tutortrack.courses.models import Enrolment
    from tutortrack.crm.models import TaggedItem
    from tutortrack.delivery.models import LessonReport
    from tutortrack.growth.models import Review
    from tutortrack.leads.models import Enquiry
    from tutortrack.learning.models import Goal, Homework
    from tutortrack.payments.models import Payment
    from tutortrack.people.models import Client, Student, TutorProfile
    from tutortrack.scheduling.models import Lesson

    MembershipFactory(organisation=org, role=Membership.Role.OWNER)
    with tenant_context(org), branch_scope(None):
        before = tenant_counts()
        real = Client.objects.count()
        loaded = demo.load_demo_data()
        assert loaded > 50

        assert Client.objects.count() - real >= 3
        assert Student.objects.filter(first_name__in=["Arjun", "Maya", "Ada"]).count() == 3
        assert TutorProfile.objects.filter(email__endswith=".sample@example.com").count() == 2
        assert Service.objects.filter(name__contains="(sample)").count() == 2
        lessons = Lesson.objects.filter(job__isnull=False)
        assert lessons.filter(status="completed").count() >= 6
        assert lessons.filter(status="planned").count() >= 6
        # Fixed local times: every 1:1 sample lesson starts on the half or full hour.
        assert {lesson.start.minute for lesson in lessons} <= {0, 30}
        assert LessonReport.objects.filter(shared_at__isnull=False).exists()
        assert LessonReport.objects.filter(status="draft").exists()
        statuses = set(Invoice.objects.values_list("status", flat=True))
        assert {"draft", "paid", "partially_paid"} <= statuses
        assert all(
            n.startswith("DEMO-")
            for n in Invoice.objects.exclude(number="").values_list("number", flat=True)
        )
        assert Payment.objects.count() == 2
        assert Enquiry.objects.count() == 4
        assert Enquiry.objects.filter(status="lost").count() == 1
        assert Enrolment.objects.count() == 2
        assert Homework.objects.count() == 1
        assert Goal.objects.count() == 1
        assert Review.objects.filter(status="approved").count() == 1
        assert TaggedItem.objects.count() >= 6
        # Nothing reaches the outside world: every sample event is already dispatched.
        assert not OutboxEvent.objects.filter(
            organisation_id=org.pk, dispatched_at__isnull=True
        ).exists()

        removed = demo.wipe_demo_data()
        assert removed == loaded
        after = tenant_counts()
        changed = {
            label: (before[label], after[label])
            for label in set(before) | set(after)
            if before[label] != after[label] and label not in NOT_WIPED
        }
        assert changed == {}
        assert not DemoRecord.objects.exists()


def test_clearing_keeps_real_records(org):
    from tutortrack.people import services as people

    with tenant_context(org):
        real, _contact, _students = people.quick_add_family(
            contact={"first_name": "Real", "last_name": "Family"}, students=[]
        )
        demo.load_demo_data()
        demo.wipe_demo_data()
        from tutortrack.people.models import Client

        assert list(Client.objects.values_list("pk", flat=True)) == [real.pk]


def test_sample_data_can_be_loaded_again_after_clearing(org):
    with tenant_context(org):
        first = demo.load_demo_data()
        demo.wipe_demo_data()
        assert demo.load_demo_data() == first

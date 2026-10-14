"""Shared fixtures for E29 Part 2 tests: a family, an owner (the default DSL), a tutor and
a plain admin (not a DSL)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.testing import client_for
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    StudentFactory,
    TutorProfileFactory,
)


@pytest.fixture
def owner(org):
    return MembershipFactory(organisation=org, role="owner").user


@pytest.fixture
def owner_api(org, owner):
    return client_for(org, owner)


@pytest.fixture
def admin_member(org):
    return MembershipFactory(organisation=org, role="admin").user


@pytest.fixture
def tutor(org):
    membership = MembershipFactory(organisation=org, role="tutor")
    return TutorProfileFactory(
        organisation=org,
        membership=membership,
        first_name="Nia",
        last_name="Adeyemi",
        email=membership.user.email,
        status="active",
    )


@pytest.fixture
def family(org):
    client = ClientFactory(organisation=org, display_name="The Patels")
    parent_user = UserFactory(email="priya@example.com", first_name="Priya", last_name="Patel")
    MembershipFactory(organisation=org, role="client", user=parent_user)
    contact = ContactFactory(
        organisation=org,
        client=client,
        first_name="Priya",
        last_name="Patel",
        email="priya@example.com",
        mobile="07700900123",
        user=parent_user,
    )
    student = StudentFactory(
        organisation=org,
        client=client,
        first_name="Arjun",
        last_name="Patel",
        date_of_birth=date(2014, 5, 1),
        school="Hill Primary",
        learning_needs="Dyslexia; extra time",
        goals="Grade 7 in maths",
    )
    with tenant_context(org):
        client.billing_contact = contact
        client.primary_contact = contact
        client.save()
    return SimpleNamespace(client=client, contact=contact, student=student, parent=parent_user)

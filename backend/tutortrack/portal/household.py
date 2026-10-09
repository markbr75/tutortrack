"""Who a portal user is and what they may see (FR-15-1): a parent sees their household
(every client their contact belongs to, and its students); a student sees only themself.
Every portal query starts from here, so another household's ids are simply not found."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.db.models import QuerySet

from tutortrack.core.context import require_organisation_id
from tutortrack.people.models import Client, Contact, Student


@dataclass
class Household:
    role: str  # client | student
    contacts: list[Contact] = field(default_factory=list)
    clients: list[Client] = field(default_factory=list)
    students: list[Student] = field(default_factory=list)

    @property
    def is_client(self) -> bool:
        return self.role == "client"

    @property
    def client_ids(self) -> list[Any]:
        return [c.pk for c in self.clients]

    @property
    def student_ids(self) -> list[Any]:
        return [s.pk for s in self.students]

    def lessons(self) -> QuerySet[Any]:
        from tutortrack.scheduling.models import Lesson

        return Lesson.objects.filter(attendees__student_id__in=self.student_ids).distinct()


def household_for(user: Any) -> Household | None:
    from tutortrack.identity.selectors import membership_for

    membership = membership_for(user, require_organisation_id())
    if membership is None or membership.status != "active":
        return None
    if membership.role == "client":
        contacts = list(Contact.objects.filter(user=user, archived_at__isnull=True))
        clients = list(
            Client.objects.filter(pk__in=[c.client_id for c in contacts], archived_at__isnull=True)
        )
        students = list(
            Student.objects.filter(client__in=clients, archived_at__isnull=True).order_by(
                "first_name"
            )
        )
        return Household("client", contacts, clients, students)
    if membership.role == "student":
        student = Student.objects.filter(user=user, archived_at__isnull=True).first()
        if student is None:
            return Household("student")
        return Household("student", [], [student.client], [student])
    return None

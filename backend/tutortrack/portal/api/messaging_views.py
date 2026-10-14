"""Portal messaging (E15-T09, FR-15-9) and makeup credits for booking.

Families (and students, when allowed) talk to the business, and to their tutors when
``portal.allow_messaging_tutors`` is on; tutors (E16) talk to the business and to the
families they teach. Everything goes through the E13 inbox (``comms.inbox``), so staff
see every message (safeguarding) and internal notes never reach the portal. Threads
outside the viewer's household (or tutor profile) are 404s.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Q, QuerySet
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from tutortrack.comms import inbox
from tutortrack.comms import selectors as comms
from tutortrack.comms.api.phase2_serializers import AttachmentSerializer
from tutortrack.comms.models import Thread, ThreadMessage
from tutortrack.core.exceptions import FeatureDisabled, NotFound, PermissionDenied
from tutortrack.core.permissions import has_perm
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from ..household import Household
from .tutor_views import TutorView
from .views import PortalView

# --- serializers --------------------------------------------------------------------------------


class PortalThreadSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    subject = serializers.CharField(allow_blank=True)
    kind = serializers.ChoiceField(choices=Thread.Kind.choices)
    with_name = serializers.CharField(allow_blank=True)
    last_message_at = serializers.DateTimeField(allow_null=True)
    last_message_preview = serializers.CharField(allow_blank=True)
    unread = serializers.IntegerField()
    closed = serializers.BooleanField()


class PortalMessageSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    author_name = serializers.CharField(allow_blank=True)
    from_business = serializers.BooleanField()
    mine = serializers.BooleanField()
    channel = serializers.CharField()
    body = serializers.CharField()
    attachments = AttachmentSerializer(many=True)
    created_at = serializers.DateTimeField()


class PortalThreadDetailSerializer(PortalThreadSerializer):
    messages = PortalMessageSerializer(many=True)


class PortalPostSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=10000)
    attachments = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list, max_length=5
    )


class PortalStartSerializer(PortalPostSerializer):
    subject = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    tutor = serializers.UUIDField(required=False, allow_null=True)
    client = serializers.UUIDField(required=False, allow_null=True)


class TutorStartSerializer(PortalPostSerializer):
    subject = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    client = serializers.UUIDField(required=False, allow_null=True)


class ContactOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class PortalMakeupCreditSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    student = serializers.UUIDField()
    student_name = serializers.CharField()
    source_lesson = serializers.CharField()
    source_start = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()


# --- helpers ------------------------------------------------------------------------------------


def _thread_row(thread: Thread, user: Any, *, viewer: str) -> dict[str, Any]:
    if viewer == "tutor":
        with_name = thread.client.display_name if thread.client_id and thread.client else ""
    else:
        with_name = (
            thread.tutor.full_name
            if thread.kind == Thread.Kind.TUTOR_FAMILY and thread.tutor
            else ""
        )
    return {
        "id": thread.pk,
        "subject": thread.subject,
        "kind": thread.kind,
        "with_name": with_name,
        "last_message_at": thread.last_message_at,
        "last_message_preview": thread.last_message_preview,
        "unread": comms.unread_count(thread, user, include_internal=False),
        "closed": comms.effective_status(thread) == Thread.Status.CLOSED,
    }


def _message_row(entry: ThreadMessage, user: Any) -> dict[str, Any]:
    return {
        "id": entry.pk,
        "author_name": entry.author_name,
        "from_business": entry.author_type == "user",
        "mine": entry.author_user_id == user.pk,
        "channel": entry.channel,
        "body": entry.body,
        "attachments": entry.attachments or [],
        "created_at": entry.created_at,
    }


def _detail(thread: Thread, user: Any, *, viewer: str) -> dict[str, Any]:
    rows = list(comms.thread_messages(thread, include_internal=False))[-300:]
    data = _thread_row(thread, user, viewer=viewer)
    inbox.mark_read(thread, user)
    data["messages"] = [_message_row(m, user) for m in rows]
    data["unread"] = 0
    return data


# --- families and students ----------------------------------------------------------------------


def messaging_features(request: Request, household: Household) -> dict[str, bool]:
    """Feature flags for ``/portal/me``."""
    allowed = bool(get_setting("portal.allow_messaging"))
    if household.is_client:
        messages = allowed and has_perm(request.user, "portal.client.message")
    else:
        messages = (
            allowed
            and bool(get_setting("portal.allow_student_messaging"))
            and has_perm(request.user, "portal.student.message")
        )
    return {
        "messages": messages,
        "message_tutors": messages and bool(get_setting("portal.allow_messaging_tutors")),
        "makeups": household.is_client and has_perm(request.user, "portal.client.book"),
    }


class MessagingView(PortalView):
    def messaging_household(self, request: Request) -> Household:
        household = self.household(request)
        if not messaging_features(request, household)["messages"]:
            raise FeatureDisabled("Messaging is turned off.")
        return household

    def author(self, request: Request, household: Household) -> inbox.Author:
        if household.is_client and household.contacts:
            contact = household.contacts[0]
            return inbox.Author("contact", str(contact.pk), contact.full_name, request.user)
        student = household.students[0] if household.students else None
        if student is None:
            raise PermissionDenied()
        return inbox.Author("student", str(student.pk), student.full_name, request.user)

    def threads(self, household: Household) -> QuerySet[Thread]:
        return comms.portal_threads(household)

    def thread(self, household: Household, thread_id: Any) -> Thread:
        found = self.threads(household).filter(pk=thread_id).first()
        if found is None:
            raise NotFound()
        return found


def household_tutors(household: Household) -> list[Any]:
    """Tutors the family may message: their students' tutors (recent or upcoming
    lessons, or active jobs)."""
    from tutortrack.jobs.models import JobTutor
    from tutortrack.people.models import TutorProfile
    from tutortrack.scheduling.models import LessonTutor

    since = now() - timedelta(days=120)
    from_lessons = LessonTutor.objects.filter(
        lesson__attendees__student_id__in=household.student_ids, lesson__start__gte=since
    ).values("tutor_id")
    from_jobs = JobTutor.objects.filter(
        job__client_id__in=household.client_ids, status="active"
    ).values("tutor_id")
    return list(
        TutorProfile.objects.filter(Q(pk__in=from_lessons) | Q(pk__in=from_jobs))
        .distinct()
        .order_by("first_name")
    )


class PortalThreadsView(MessagingView):
    @extend_schema(responses=PortalThreadSerializer(many=True))
    def get(self, request: Request) -> Response:
        household = self.messaging_household(request)
        rows = self.threads(household).order_by("-last_message_at")[:100]
        return Response([_thread_row(t, request.user, viewer="family") for t in rows])

    @extend_schema(
        request=PortalStartSerializer,
        responses={201: PortalThreadDetailSerializer},
        examples=[
            OpenApiExample(
                "Ask the office",
                value={"subject": "Thursday", "body": "Could Sam start at 5pm this week?"},
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        """Start a conversation with the business, or with one of your tutors (if your
        tutoring company allows it)."""
        household = self.messaging_household(request)
        payload = PortalStartSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        client = household.clients[0] if household.clients else None
        if data.get("client"):
            client = next((c for c in household.clients if c.pk == data["client"]), None)
        if client is None:
            raise NotFound()
        tutor = None
        if data.get("tutor"):
            if not messaging_features(request, household)["message_tutors"]:
                raise FeatureDisabled("Messaging tutors is turned off.")
            tutor = next((t for t in household_tutors(household) if t.pk == data["tutor"]), None)
            if tutor is None:
                raise NotFound()
        student = household.students[0] if not household.is_client and household.students else None
        thread = inbox.start_from_portal(
            self.author(request, household),
            kind=Thread.Kind.TUTOR_FAMILY if tutor else Thread.Kind.CLIENT,
            body=data["body"],
            subject=data["subject"],
            client=client,
            tutor=tutor,
            student=student,
            attachments=data["attachments"],
        )
        return Response(
            _detail(thread, request.user, viewer="family"), status=status.HTTP_201_CREATED
        )


class PortalThreadView(MessagingView):
    @extend_schema(responses=PortalThreadDetailSerializer)
    def get(self, request: Request, thread_id: Any) -> Response:
        household = self.messaging_household(request)
        return Response(_detail(self.thread(household, thread_id), request.user, viewer="family"))


class PortalThreadMessagesView(MessagingView):
    @extend_schema(request=PortalPostSerializer, responses={201: PortalMessageSerializer})
    def post(self, request: Request, thread_id: Any) -> Response:
        household = self.messaging_household(request)
        thread = self.thread(household, thread_id)
        payload = PortalPostSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        entry = inbox.post_from_portal(
            thread,
            self.author(request, household),
            body=payload.validated_data["body"],
            attachments=payload.validated_data["attachments"],
        )
        return Response(_message_row(entry, request.user), status=status.HTTP_201_CREATED)


class PortalMessageTutorsView(MessagingView):
    @extend_schema(responses=ContactOptionSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Tutors you can message (empty unless messaging tutors is allowed)."""
        household = self.messaging_household(request)
        if not messaging_features(request, household)["message_tutors"]:
            return Response([])
        return Response([{"id": t.pk, "name": t.full_name} for t in household_tutors(household)])


class PortalMakeupCreditsView(PortalView):
    @extend_schema(responses=PortalMakeupCreditSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Unused makeup credits the family can book a lesson with (E09, FR-15-5)."""
        from tutortrack.delivery.models import MakeupCredit

        household = self.client_household(request, "portal.client.book")
        moment = now()
        credits = (
            MakeupCredit.objects.filter(
                student_id__in=household.student_ids,
                consumed_by_lesson__isnull=True,
                voided_at__isnull=True,
                expires_at__gt=moment,
            )
            .select_related("student", "source_lesson")
            .order_by("expires_at")
        )
        return Response(
            [
                {
                    "id": c.pk,
                    "student": c.student_id,
                    "student_name": c.student.full_name,
                    "source_lesson": c.source_lesson.title,
                    "source_start": c.source_lesson.start,
                    "expires_at": c.expires_at,
                }
                for c in credits
            ]
        )


# --- tutors (E16 shell) -------------------------------------------------------------------------


class TutorMessagingView(TutorView):
    def tutor_messaging(self, request: Request) -> Any:
        if not has_perm(request.user, "comms.inbox.reply"):
            raise PermissionDenied()
        return self.tutor(request)

    def thread(self, tutor: Any, thread_id: Any) -> Thread:
        found = comms.tutor_threads(tutor).filter(pk=thread_id).first()
        if found is None:
            raise NotFound()
        return found


def tutor_families(tutor: Any) -> list[Any]:
    from tutortrack.jobs.models import JobTutor
    from tutortrack.people.models import Client
    from tutortrack.scheduling.models import LessonAttendee

    since = now() - timedelta(days=120)
    from_lessons = LessonAttendee.objects.filter(
        lesson__tutors__tutor=tutor, lesson__start__gte=since
    ).values("student__client_id")
    from_jobs = JobTutor.objects.filter(tutor=tutor, status="active").values("job__client_id")
    return list(
        Client.objects.filter(
            Q(pk__in=from_lessons) | Q(pk__in=from_jobs), archived_at__isnull=True
        )
        .distinct()
        .order_by("display_name")
    )


class TutorThreadsView(TutorMessagingView):
    @extend_schema(responses=PortalThreadSerializer(many=True))
    def get(self, request: Request) -> Response:
        tutor = self.tutor_messaging(request)
        rows = comms.tutor_threads(tutor).order_by("-last_message_at")[:100]
        return Response([_thread_row(t, request.user, viewer="tutor") for t in rows])

    @extend_schema(request=TutorStartSerializer, responses={201: PortalThreadDetailSerializer})
    def post(self, request: Request) -> Response:
        """Message the office, or a family you teach (if allowed)."""
        tutor = self.tutor_messaging(request)
        payload = TutorStartSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        client = None
        if data.get("client"):
            if not get_setting("portal.allow_messaging_tutors"):
                raise FeatureDisabled("Messaging families is turned off.")
            client = next((c for c in tutor_families(tutor) if c.pk == data["client"]), None)
            if client is None:
                raise NotFound()
        author = inbox.Author("tutor", str(tutor.pk), tutor.full_name, request.user)
        thread = inbox.start_from_portal(
            author,
            kind=Thread.Kind.TUTOR_FAMILY if client else Thread.Kind.TUTOR,
            body=data["body"],
            subject=data["subject"],
            client=client,
            tutor=tutor,
            attachments=data["attachments"],
        )
        return Response(
            _detail(thread, request.user, viewer="tutor"), status=status.HTTP_201_CREATED
        )


class TutorThreadView(TutorMessagingView):
    @extend_schema(responses=PortalThreadDetailSerializer)
    def get(self, request: Request, thread_id: Any) -> Response:
        tutor = self.tutor_messaging(request)
        return Response(_detail(self.thread(tutor, thread_id), request.user, viewer="tutor"))


class TutorThreadMessagesView(TutorMessagingView):
    @extend_schema(request=PortalPostSerializer, responses={201: PortalMessageSerializer})
    def post(self, request: Request, thread_id: Any) -> Response:
        tutor = self.tutor_messaging(request)
        thread = self.thread(tutor, thread_id)
        payload = PortalPostSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        author = inbox.Author("tutor", str(tutor.pk), tutor.full_name, request.user)
        entry = inbox.post_from_portal(
            thread,
            author,
            body=payload.validated_data["body"],
            attachments=payload.validated_data["attachments"],
        )
        return Response(_message_row(entry, request.user), status=status.HTTP_201_CREATED)


class TutorMessageFamiliesView(TutorMessagingView):
    @extend_schema(responses=ContactOptionSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Families you can message (empty unless tutor-family messaging is allowed)."""
        tutor = self.tutor_messaging(request)
        if not get_setting("portal.allow_messaging_tutors"):
            return Response([])
        return Response([{"id": c.pk, "name": c.display_name} for c in tutor_families(tutor)])

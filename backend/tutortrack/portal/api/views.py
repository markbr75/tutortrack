"""Client and student portal API (E15 §3). Every view resolves the viewer's household
first; records outside it are 404s, even with a guessed id."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import QuerySet
from django.http import HttpResponse
from django.utils.dateparse import parse_date, parse_datetime
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import FeatureDisabled, NotFound, PermissionDenied
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, has_perm
from tutortrack.core.time import now
from tutortrack.people.models import Contact, Student
from tutortrack.tenancy.settings_service import get_setting

from .. import selectors, services
from ..household import Household, household_for
from ..models import Announcement
from . import serializers as s


class PortalUser(BasePermission):
    def has_permission(self, request: Request, view: Any) -> bool:
        return has_perm(request.user, "portal.client.view") or has_perm(
            request.user, "portal.student.view"
        )


AUTH = [IsAuthenticated, HasOrganisation, PortalUser]


def setting(key: str) -> bool:
    return bool(get_setting(key))


class PortalView(APIView):
    permission_classes = AUTH

    def household(self, request: Request) -> Household:
        if not setting("portal.enabled"):
            raise FeatureDisabled("The portal is turned off.")
        found = household_for(request.user)
        if found is None:
            raise PermissionDenied()
        return found

    def client_household(self, request: Request, codename: str = "portal.client.view") -> Household:
        household = self.household(request)
        if not household.is_client or not has_perm(request.user, codename):
            raise PermissionDenied()
        return household

    def lesson(self, household: Household, lesson_id: Any) -> Any:
        lesson = selectors.lessons(household).filter(pk=lesson_id).first()
        if lesson is None:
            raise NotFound()
        return lesson


def _range(request: Request) -> tuple[Any, Any]:
    start = parse_datetime(request.query_params.get("start") or "") or now() - timedelta(days=7)
    end = parse_datetime(request.query_params.get("end") or "") or start + timedelta(days=42)
    if end - start > timedelta(days=93):
        end = start + timedelta(days=93)
    return start, end


class MeView(PortalView):
    @extend_schema(responses=s.PortalMeSerializer)
    def get(self, request: Request) -> Response:
        from tutortrack.core.context import require_organisation_id
        from tutortrack.tenancy.models import Organisation

        household = self.household(request)
        org = Organisation.objects.get(pk=require_organisation_id())
        return Response(
            {
                "role": household.role,
                "organisation": {"name": org.name, "primary_colour": org.primary_colour},
                "clients": [{"id": str(c.pk), "name": c.display_name} for c in household.clients],
                "students": [{"id": str(st.pk), "name": st.full_name} for st in household.students],
                "features": {
                    "cancellations": setting("portal.allow_cancellations")
                    and has_perm(request.user, "portal.client.cancel"),
                    "absence": setting("portal.allow_absence")
                    and has_perm(request.user, "portal.client.cancel"),
                    "invoices": setting("portal.show_invoices") and household.is_client,
                    "reports": setting("portal.show_reports"),
                    "profile": setting("portal.allow_profile_edits") and household.is_client,
                },
                "welcome_text": str(get_setting("portal.welcome_text")),
                "help_url": str(get_setting("portal.help_url")),
                "terms_url": str(get_setting("portal.terms_url")),
            }
        )


class DashboardView(PortalView):
    @extend_schema(responses=s.DashboardSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.DashboardSerializer(selectors.dashboard(self.household(request))).data)


class ScheduleView(PortalView):
    @extend_schema(
        responses=s.PortalLessonSerializer(many=True),
        parameters=[
            OpenApiParameter("start", OpenApiTypes.DATETIME),
            OpenApiParameter("end", OpenApiTypes.DATETIME),
            OpenApiParameter("student", str),
        ],
    )
    def get(self, request: Request) -> Response:
        household = self.household(request)
        start, end = _range(request)
        rows = selectors.schedule(household, start, end, request.query_params.get("student"))
        return Response(s.PortalLessonSerializer(rows, many=True).data)


class LessonIcsView(PortalView):
    @extend_schema(responses={(200, "text/calendar"): OpenApiTypes.STR})
    def get(self, request: Request, lesson_id: Any) -> HttpResponse:
        from tutortrack.scheduling import ical

        lesson = self.lesson(self.household(request), lesson_id)
        body = ical.render([lesson], name=lesson.title, host=request.get_host())
        response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="lesson.ics"'
        return response


class CancelView(PortalView):
    @extend_schema(
        request=s.PortalCancelSerializer,
        responses=s.PortalCancelResultSerializer,
        parameters=[OpenApiParameter("preview", bool)],
    )
    def post(self, request: Request, lesson_id: Any) -> Response:
        """Cancel a household lesson; ``?preview=true`` shows the fee first (FR-15-4)."""
        from tutortrack.delivery import services as delivery

        household = self.client_household(request, "portal.client.cancel")
        if not setting("portal.allow_cancellations"):
            raise FeatureDisabled("Cancelling online is turned off.")
        lesson = self.lesson(household, lesson_id)
        if lesson.start <= now():
            raise PermissionDenied("Lessons that have started can't be cancelled here.")
        payload = s.PortalCancelSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        preview = request.query_params.get("preview") in {"1", "true"}
        result = delivery.cancel_lesson(
            lesson,
            user=request.user,
            cancelled_by="client",
            reason=payload.validated_data["reason"],
            preview=preview,
        )
        return Response(
            {
                "kind": result.decision.kind,
                "charge_percent": result.charge_percent,
                "message": result.decision.message,
                "makeup_credit": result.decision.makeup_credit,
                "cancelled": not preview,
            }
        )


class AbsenceView(PortalView):
    @extend_schema(request=s.AbsenceSerializer, responses={204: None})
    def post(self, request: Request, lesson_id: Any) -> Response:
        """ "Sam is ill today": a lesson only for them is cancelled under the policy; in a
        group lesson they are marked absent (FR-15-4)."""
        from tutortrack.delivery import services as delivery

        household = self.client_household(request, "portal.client.cancel")
        if not setting("portal.allow_absence"):
            raise FeatureDisabled("Reporting absences online is turned off.")
        lesson = self.lesson(household, lesson_id)
        payload = s.AbsenceSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        student = next(
            (
                st
                for st in household.students
                if str(st.pk) == str(payload.validated_data["student"])
            ),
            None,
        )
        if student is None:
            raise NotFound()
        delivery.notify_absence(
            lesson, student, note=payload.validated_data["note"], user=request.user
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReportsView(PortalView):
    @extend_schema(
        responses=s.PortalReportSerializer(many=True),
        parameters=[OpenApiParameter("student", str)],
    )
    def get(self, request: Request) -> Response:
        household = self.household(request)
        if not setting("portal.show_reports"):
            raise FeatureDisabled("Reports aren't shared in the portal.")
        qs = selectors.shared_reports(household)
        student = request.query_params.get("student")
        if student:
            qs = qs.filter(lesson__attendees__student_id=student)
        rows = [selectors.report_out(r, household) for r in qs.prefetch_related("comments")[:50]]
        return Response(s.PortalReportSerializer(rows, many=True).data)


class ReportCommentView(PortalView):
    @extend_schema(request=s.ReportReplySerializer, responses={201: s.PortalReportSerializer})
    def post(self, request: Request, report_id: Any) -> Response:
        from tutortrack.delivery import services as delivery

        household = self.household(request)
        report = selectors.shared_reports(household).filter(pk=report_id).first()
        if report is None:
            raise NotFound()
        payload = s.ReportReplySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        delivery.add_comment(
            report, user=request.user, body=payload.validated_data["body"], visibility="client"
        )
        return Response(
            s.PortalReportSerializer(selectors.report_out(report, household)).data,
            status=status.HTTP_201_CREATED,
        )


class BillingView(PortalView):
    @extend_schema(responses=s.PortalBillingSerializer)
    def get(self, request: Request) -> Response:
        household = self.client_household(request)
        if not setting("portal.show_invoices"):
            raise FeatureDisabled("Invoices aren't shown in the portal.")
        return Response(s.PortalBillingSerializer(selectors.billing(household)).data)


class StatementView(PortalView):
    @extend_schema(
        responses={(200, "application/pdf"): OpenApiTypes.BINARY},
        parameters=[
            OpenApiParameter("client", str),
            OpenApiParameter("from", OpenApiTypes.DATE),
            OpenApiParameter("to", OpenApiTypes.DATE),
        ],
    )
    def get(self, request: Request) -> HttpResponse:
        from tutortrack.billing import pdf
        from tutortrack.billing import selectors as billing
        from tutortrack.core.context import require_organisation_id
        from tutortrack.tenancy.models import Organisation

        household = self.client_household(request)
        wanted = request.query_params.get("client")
        client = next((c for c in household.clients if str(c.pk) == wanted), None)
        if client is None:
            raise NotFound()
        end = parse_date(request.query_params.get("to") or "") or now().date()
        start = parse_date(request.query_params.get("from") or "") or end - timedelta(days=90)
        org = Organisation.objects.get(pk=require_organisation_id())
        data = billing.statement(client, client.currency, start, end, org.timezone)
        response = HttpResponse(pdf.statement_pdf(client, data), content_type="application/pdf")
        response["Content-Disposition"] = 'inline; filename="statement.pdf"'
        return response


def _client_of(household: Household, client_id: Any) -> Any:
    client = next((c for c in household.clients if str(c.pk) == str(client_id)), None)
    if client is None:
        raise NotFound()
    return client


class PaymentMethodsView(PortalView):
    @extend_schema(
        responses=s.PortalMethodsSerializer, parameters=[OpenApiParameter("client", str)]
    )
    def get(self, request: Request) -> Response:
        from tutortrack.payments.models import AutoPayConsent, PaymentMethod

        household = self.client_household(request, "portal.client.pay")
        client = _client_of(household, request.query_params.get("client"))
        consent = AutoPayConsent.objects.filter(client=client, withdrawn_at__isnull=True).first()
        methods = PaymentMethod.objects.filter(client=client, status="active")
        return Response(
            {
                "auto_pay": client.auto_pay,
                "consent_given_at": consent.given_at if consent else None,
                "methods": s.PortalMethodSerializer(methods, many=True).data,
            }
        )

    @extend_schema(request=s.PortalMethodActionSerializer, responses=s.PortalSetupSerializer)
    def post(self, request: Request) -> Response:
        """``action``: ``add`` (a link to save a card or mandate), ``default``,
        ``remove`` or ``autopay_off``."""
        from tutortrack.payments import services as payments
        from tutortrack.payments.models import PaymentMethod

        household = self.client_household(request, "portal.client.pay")
        payload = s.PortalMethodActionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        client = _client_of(household, data["client"])
        if data["action"] == "add":
            return Response({"url": payments.create_setup_link(client, user=request.user)})
        if data["action"] == "autopay_off":
            payments.set_autopay(client, False, user=request.user)
            return Response({"url": ""})
        method = PaymentMethod.objects.filter(
            pk=data.get("method"), client=client, status="active"
        ).first()
        if method is None:
            raise NotFound()
        if data["action"] == "default":
            payments.set_default_method(method)
        else:
            payments.remove_method(method, user=request.user)
        return Response({"url": ""})


class ProfileView(PortalView):
    @extend_schema(responses=s.PortalProfileSerializer)
    def get(self, request: Request) -> Response:
        household = self.client_household(request)
        return Response(
            s.PortalProfileSerializer(
                {"contacts": household.contacts, "students": household.students}
            ).data
        )


class ContactProfileView(PortalView):
    @extend_schema(request=s.PortalContactSerializer, responses=s.PortalContactSerializer)
    def patch(self, request: Request, contact_id: Any) -> Response:
        household = self.client_household(request, "portal.client.profile")
        if not setting("portal.allow_profile_edits"):
            raise FeatureDisabled("Profile changes are turned off.")
        contact = next((c for c in household.contacts if str(c.pk) == str(contact_id)), None)
        if contact is None:
            raise NotFound()
        payload = s.PortalContactSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        services.update_contact(contact, **payload.validated_data)
        return Response(s.PortalContactSerializer(contact).data)


class StudentProfileView(PortalView):
    @extend_schema(request=s.PortalStudentSerializer, responses=s.PortalStudentSerializer)
    def patch(self, request: Request, student_id: Any) -> Response:
        household = self.client_household(request, "portal.client.profile")
        if not setting("portal.allow_profile_edits"):
            raise FeatureDisabled("Profile changes are turned off.")
        student = next((st for st in household.students if str(st.pk) == str(student_id)), None)
        if student is None:
            raise NotFound()
        payload = s.PortalStudentSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        services.update_student(student, **payload.validated_data)
        return Response(s.PortalStudentSerializer(student).data)


# --- staff: announcements and portal invitations ------------------------------------------------


class AnnouncementViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """News posts for the portals (E15-T07)."""

    model = Announcement
    serializer_class = s.AnnouncementSerializer
    http_method_names = ["get", "post", "put", "delete", "head", "options"]
    permission_classes = [
        IsAuthenticated,
        HasOrganisation,
        HasMethodPermission.for_(
            {
                "GET": "comms.announcement.manage",
                "POST": "comms.announcement.manage",
                "PUT": "comms.announcement.manage",
                "DELETE": "comms.announcement.manage",
            }
        ),
    ]

    def get_tenant_queryset(self) -> QuerySet[Announcement]:
        return Announcement.objects.all()

    def create(self, request: Request) -> Response:
        payload = self.get_serializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row = services.save_announcement(user=request.user, **payload.validated_data)
        return Response(self.get_serializer(row).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, pk: Any = None) -> Response:
        payload = self.get_serializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row = services.save_announcement(announcement=self.get_object(), **payload.validated_data)
        return Response(self.get_serializer(row).data)


class PortalAnnouncementsView(PortalView):
    @extend_schema(responses=s.AnnouncementSerializer(many=True))
    def get(self, request: Request) -> Response:
        rows = selectors.announcements(self.household(request))[:20]
        return Response(s.AnnouncementSerializer(rows, many=True).data)


class InviteView(APIView):
    """Invite a contact (parent) or student to the portal."""

    permission_classes = [
        IsAuthenticated,
        HasOrganisation,
        HasMethodPermission.for_({"POST": "people.client.edit"}),
    ]

    @extend_schema(request=s.InviteSerializer, responses={201: s.InviteResultSerializer})
    def post(self, request: Request, kind: str, record_id: Any) -> Response:
        from tutortrack.core.permissions import scope_queryset
        from tutortrack.people import services as people

        model = {"contacts": Contact, "students": Student}.get(kind)
        if model is None:
            raise NotFound()
        perm = "people.client.view" if model is Contact else "people.student.view"
        record = (
            scope_queryset(request.user, model.objects.all(), perm).filter(pk=record_id).first()
        )
        if record is None:
            raise NotFound()
        payload = s.InviteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        invitation = people.invite_to_portal(record, email=payload.validated_data["email"])
        return Response(
            {"email": invitation.email, "expires_at": invitation.expires_at},
            status=status.HTTP_201_CREATED,
        )

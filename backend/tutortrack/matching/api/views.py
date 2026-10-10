"""Matching and job marketplace API (E19 §4)."""

from __future__ import annotations

from typing import Any

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import PermissionDenied
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, has_perm
from tutortrack.jobs.models import Job
from tutortrack.people.assignability import override_from_request
from tutortrack.people.models import TutorProfile
from tutortrack.scheduling.models import Lesson

from .. import engine, selectors, services
from ..models import (
    CoverRequest,
    JobOffer,
    JobPosting,
    JobPostingApplication,
    OfferBatch,
    Shortlist,
)
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


def _my_tutor(request: Request) -> TutorProfile:
    tutor = TutorProfile.objects.filter(membership__user=request.user).first()
    if tutor is None:
        raise NotFound("You're not a tutor here.")
    return tutor


def _job(user: Any, pk: Any) -> Job:
    return get_object_or_404(selectors.visible_jobs(user), pk=pk)


def _row(rank: int, match: engine.Match, shortlisted: set[str]) -> dict[str, Any]:
    point = match.point
    return {
        "rank": rank,
        "tutor": {
            "id": match.tutor.pk,
            "name": match.tutor.full_name,
            "headline": match.tutor.headline,
            "status": match.tutor.status,
        },
        "score": match.score,
        "breakdown": match.breakdown,
        "distance_km": round(match.distance_km, 1) if match.distance_km is not None else None,
        "slot_fit": match.slot_fit,
        "restricted": match.restricted,
        "reasons": match.reasons,
        "point": {"lat": point[0], "lng": point[1]} if point else None,
        "shortlisted": str(match.tutor.pk) in shortlisted,
    }


# --- search, settings, analytics ----------------------------------------------------------------


class MatchSearchView(APIView):
    permission_classes = perms({"POST": "matching.search"})

    @extend_schema(request=s.MatchSearchSerializer, responses=s.MatchSearchResultSerializer)
    def post(self, request: Request) -> Response:
        """Ranked tutors for a job or ad hoc criteria, with each factor's score. "Include
        restricted" needs ``matching.include_restricted``."""
        payload = s.MatchSearchSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        include = data["include_restricted"]
        if include and not has_perm(request.user, "matching.include_restricted"):
            raise PermissionDenied("You can't include restricted tutors.")
        job = _job(request.user, data["job"]) if data.get("job") else None
        criteria = engine.criteria_from_input(data, job)
        query, matches = services.run_search(
            criteria, include_restricted=include, limit=data["limit"], job=job
        )
        shortlisted = (
            {str(t) for t in Shortlist.objects.filter(job=job).values_list("tutor_id", flat=True)}
            if job is not None
            else set()
        )
        origin = (
            {"lat": float(criteria.lat), "lng": float(criteria.lng)}
            if criteria.lat is not None and criteria.lng is not None
            else None
        )
        body = {
            "query": query.pk,
            "criteria": query.criteria,
            "origin": origin,
            "results": [_row(i, m, shortlisted) for i, m in enumerate(matches, start=1)],
        }
        return Response(s.MatchSearchResultSerializer(body).data)


class MatchingSettingsView(APIView):
    permission_classes = perms({"GET": "matching.search", "PUT": "matching.settings.manage"})

    @extend_schema(responses=s.MatchingWeightsSerializer)
    def get(self, request: Request) -> Response:
        return Response({"weights": engine._weights()})

    @extend_schema(request=s.MatchingWeightsSerializer, responses=s.MatchingWeightsSerializer)
    def put(self, request: Request) -> Response:
        payload = s.MatchingWeightsSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return Response({"weights": services.set_weights(payload.validated_data["weights"])})


class MatchingAnalyticsView(APIView):
    permission_classes = perms({"GET": "matching.analytics.view"})

    @extend_schema(
        parameters=[OpenApiParameter("days", int, required=False)],
        responses=s.MatchingAnalyticsSerializer,
    )
    def get(self, request: Request) -> Response:
        try:
            days = min(max(int(request.query_params.get("days", 90)), 1), 730)
        except ValueError:
            days = 90
        return Response(s.MatchingAnalyticsSerializer(selectors.analytics(days=days)).data)


# --- shortlists ---------------------------------------------------------------------------------


class ShortlistViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Tutors shortlisted for jobs (``?job=``)."""

    model = Shortlist
    serializer_class = s.ShortlistSerializer
    pagination_class = None
    permission_classes = perms(
        {
            "GET": "matching.search",
            "POST": "matching.offer.manage",
            "DELETE": "matching.offer.manage",
        }
    )

    def get_tenant_queryset(self) -> Any:
        qs = Shortlist.objects.filter(job__in=selectors.visible_jobs(self.request.user))
        job = self.request.query_params.get("job")
        return qs.filter(job_id=job).select_related("tutor") if job else qs.select_related("tutor")

    @extend_schema(parameters=[OpenApiParameter("job", str, required=False)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.ShortlistSerializer(data=request.data, context={"request": request})
        payload.is_valid(raise_exception=True)
        job = _job(request.user, payload.validated_data["job"].pk)
        entry = services.shortlist_add(
            job, payload.validated_data["tutor"], note=payload.validated_data.get("note", "")
        )
        return Response(s.ShortlistSerializer(entry).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance: Shortlist) -> None:
        services.shortlist_remove(instance)


# --- offers -------------------------------------------------------------------------------------


class OfferBatchViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Job offers sent to tutors, in batches (``?job=``)."""

    model = OfferBatch
    serializer_class = s.OfferBatchSerializer
    permission_classes = perms({"*": "matching.offer.manage"})

    def get_tenant_queryset(self) -> Any:
        qs = selectors.batches(self.request.user)
        job = self.request.query_params.get("job")
        return qs.filter(job_id=job) if job else qs

    @extend_schema(parameters=[OpenApiParameter("job", str, required=False)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(request=s.StartOffersSerializer, responses={201: s.OfferBatchSerializer})
    def create(self, request: Request) -> Response:
        """Offer the job to the tutors: everyone at once, or one after another."""
        payload = s.StartOffersSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        job = _job(request.user, data["job"])
        tutors = {str(t.pk): t for t in TutorProfile.objects.filter(pk__in=data["tutors"])}
        missing = [str(t) for t in data["tutors"] if str(t) not in tutors]
        if missing:
            raise NotFound("Tutor not found.")
        with override_from_request(request):
            batch = services.start_offers(
                job,
                [tutors[str(t)] for t in data["tutors"]],
                mode=data["mode"],
                expiry_hours=data.get("expiry_hours"),
                admin_confirms=data.get("admin_confirms"),
                pay_rate=data.get("pay_rate"),
            )
        return Response(
            s.OfferBatchSerializer(selectors.batches(request.user).get(pk=batch.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=None, responses=s.OfferBatchSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        batch = services.cancel_batch(self.get_object())
        return Response(
            s.OfferBatchSerializer(selectors.batches(request.user).get(pk=batch.pk)).data
        )

    @extend_schema(request=s.DecideSerializer, responses=s.OfferBatchSerializer)
    @action(detail=True, methods=["post"])
    def decide(self, request: Request, pk: Any = None) -> Response:
        """Confirm (or turn down) the tutor who accepted, when offers need confirmation."""
        payload = s.DecideSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        batch = services.decide(
            self.get_object(),
            approve=payload.validated_data["approve"],
            reason=payload.validated_data["reason"],
        )
        return Response(
            s.OfferBatchSerializer(selectors.batches(request.user).get(pk=batch.pk)).data
        )


class JobOfferWithdrawView(APIView):
    permission_classes = perms({"POST": "matching.offer.manage"})

    @extend_schema(request=None, responses=s.JobOfferSerializer)
    def post(self, request: Request, pk: Any) -> Response:
        offer = get_object_or_404(
            JobOffer.objects.filter(job__in=selectors.visible_jobs(request.user)), pk=pk
        )
        return Response(s.JobOfferSerializer(services.withdraw_offer(offer)).data)


class MyJobOffersView(APIView):
    permission_classes = AUTH

    @extend_schema(responses=s.MyJobOfferSerializer(many=True))
    def get(self, request: Request) -> Response:
        offers = selectors.my_offers(_my_tutor(request))[:100]
        return Response(s.MyJobOfferSerializer(offers, many=True).data)


class MyJobOfferAnswerView(APIView):
    permission_classes = AUTH

    @extend_schema(request=s.DeclineOfferSerializer, responses=s.MyJobOfferSerializer)
    def post(self, request: Request, pk: Any, answer: str) -> Response:
        tutor = _my_tutor(request)
        offer = get_object_or_404(JobOffer.objects.filter(tutor=tutor), pk=pk)
        payload = s.DeclineOfferSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        offer = services.respond(
            offer, accept=answer == "accept", reason=payload.validated_data["reason"]
        )
        return Response(s.MyJobOfferSerializer(offer).data)


# --- job board ----------------------------------------------------------------------------------


class JobPostingViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Jobs on the internal job board and their applicants (``?job=``)."""

    model = JobPosting
    permission_classes = perms({"GET": "matching.search", "POST": "matching.posting.manage"})

    def get_tenant_queryset(self) -> Any:
        qs = selectors.postings(self.request.user)
        job = self.request.query_params.get("job")
        return qs.filter(job_id=job) if job else qs

    def get_serializer_class(self) -> Any:
        return s.JobPostingDetailSerializer if self.action == "retrieve" else s.JobPostingSerializer

    @extend_schema(parameters=[OpenApiParameter("job", str, required=False)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=s.PublishPostingSerializer, responses={201: s.JobPostingDetailSerializer}
    )
    def create(self, request: Request) -> Response:
        """Put the job on the job board for eligible tutors."""
        payload = s.PublishPostingSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        posting = services.publish_posting(
            _job(request.user, data["job"]),
            title=data["title"],
            min_score=data["min_score"],
            closes_on=data.get("closes_on"),
        )
        return Response(s.JobPostingDetailSerializer(posting).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=s.JobPostingDetailSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request: Request, pk: Any = None) -> Response:
        return Response(
            s.JobPostingDetailSerializer(services.close_posting(self.get_object())).data
        )

    def _application(self, app_id: str) -> JobPostingApplication:
        return get_object_or_404(
            JobPostingApplication.objects.filter(posting=self.get_object()), pk=app_id
        )

    @extend_schema(request=None, responses=s.JobPostingDetailSerializer)
    @action(detail=True, methods=["post"], url_path=r"applications/(?P<app_id>[0-9a-f-]+)/select")
    def select(self, request: Request, pk: Any = None, app_id: str = "") -> Response:
        """Choose this applicant: they're assigned and the others are told."""
        application = services.select_applicant(self._application(app_id))
        posting = JobPosting.objects.get(pk=application.posting_id)
        return Response(s.JobPostingDetailSerializer(posting).data)

    @extend_schema(request=None, responses=s.JobPostingDetailSerializer)
    @action(detail=True, methods=["post"], url_path=r"applications/(?P<app_id>[0-9a-f-]+)/reject")
    def reject(self, request: Request, pk: Any = None, app_id: str = "") -> Response:
        application = services.reject_applicant(self._application(app_id))
        posting = JobPosting.objects.get(pk=application.posting_id)
        return Response(s.JobPostingDetailSerializer(posting).data)


class MyJobPostingsView(APIView):
    permission_classes = AUTH

    @extend_schema(responses=s.MyPostingSerializer(many=True))
    def get(self, request: Request) -> Response:
        tutor = _my_tutor(request)
        rows = selectors.my_postings(tutor)[:100]
        return Response(s.MyPostingSerializer(rows, many=True, context={"tutor": tutor}).data)


class MyJobPostingApplyView(APIView):
    permission_classes = AUTH

    @extend_schema(request=s.ApplyPostingSerializer, responses=s.MyPostingSerializer)
    def post(self, request: Request, pk: Any) -> Response:
        tutor = _my_tutor(request)
        posting = get_object_or_404(selectors.my_postings(tutor), pk=pk)
        payload = s.ApplyPostingSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.apply_to_posting(
            posting,
            tutor,
            message=payload.validated_data["message"],
            proposed_availability=payload.validated_data.get("proposed_availability"),
        )
        return Response(
            s.MyPostingSerializer(posting, context={"tutor": tutor}).data,
            status=status.HTTP_201_CREATED,
        )


# --- cover --------------------------------------------------------------------------------------


def _cover_qs() -> Any:
    return CoverRequest.objects.select_related("original_tutor", "accepted_by").prefetch_related(
        "lessons__lesson"
    )


class CoverRequestViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Cover requests for lessons (``?status=``)."""

    model = CoverRequest
    serializer_class = s.CoverRequestSerializer
    permission_classes = perms({"*": "matching.cover.manage"})

    def get_tenant_queryset(self) -> Any:
        qs = _cover_qs()
        state = self.request.query_params.get("status")
        return qs.filter(status=state) if state else qs

    @extend_schema(parameters=[OpenApiParameter("status", str, required=False)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(request=s.CreateCoverSerializer, responses={201: s.CoverRequestSerializer})
    def create(self, request: Request) -> Response:
        payload = s.CreateCoverSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        lessons = list(Lesson.objects.filter(pk__in=payload.validated_data["lessons"]))
        if len(lessons) != len(set(payload.validated_data["lessons"])):
            raise NotFound("Lesson not found.")
        cover = services.create_cover(lessons, reason=payload.validated_data["reason"])
        return Response(
            s.CoverRequestSerializer(_cover_qs().get(pk=cover.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=None, responses=s.CoverRequestSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        cover = services.cancel_cover(self.get_object())
        return Response(s.CoverRequestSerializer(_cover_qs().get(pk=cover.pk)).data)

    @extend_schema(request=s.AssignCoverSerializer, responses=s.CoverRequestSerializer)
    @action(detail=True, methods=["post"])
    def assign(self, request: Request, pk: Any = None) -> Response:
        """Give the cover to a tutor directly."""
        payload = s.AssignCoverSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        tutor = get_object_or_404(TutorProfile.objects.all(), pk=payload.validated_data["tutor"])
        with override_from_request(request):
            cover = services.accept_cover(self.get_object(), tutor, by_staff=True)
        return Response(s.CoverRequestSerializer(_cover_qs().get(pk=cover.pk)).data)

    @extend_schema(request=None, responses=s.MatchRowSerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def candidates(self, request: Request, pk: Any = None) -> Response:
        """Tutors free for every lesson, best first."""
        matches = services.cover_candidates(self.get_object(), limit=25)
        rows = [_row(i, m, set()) for i, m in enumerate(matches, start=1)]
        return Response(s.MatchRowSerializer(rows, many=True).data)


class MyCoverRequestsView(APIView):
    permission_classes = AUTH

    @extend_schema(responses=s.CoverRequestSerializer(many=True))
    def get(self, request: Request) -> Response:
        rows = selectors.my_cover(_my_tutor(request))[:100]
        return Response(s.CoverRequestSerializer(rows, many=True).data)

    @extend_schema(request=s.CreateCoverSerializer, responses={201: s.CoverRequestSerializer})
    def post(self, request: Request) -> Response:
        """A tutor asks for cover for their own lessons."""
        tutor = _my_tutor(request)
        payload = s.CreateCoverSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        lessons = list(
            Lesson.objects.filter(pk__in=payload.validated_data["lessons"], tutors__tutor=tutor)
        )
        if len(lessons) != len(set(payload.validated_data["lessons"])):
            raise NotFound("Lesson not found.")
        cover = services.create_cover(lessons, reason=payload.validated_data["reason"], tutor=tutor)
        return Response(
            s.CoverRequestSerializer(_cover_qs().get(pk=cover.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class MyCoverAcceptView(APIView):
    permission_classes = AUTH

    @extend_schema(request=None, responses=s.CoverRequestSerializer)
    def post(self, request: Request, pk: Any) -> Response:
        tutor = _my_tutor(request)
        cover = get_object_or_404(_cover_qs(), pk=pk)
        if tutor.pk == cover.original_tutor_id or str(tutor.pk) not in (cover.notified or []):
            raise NotFound("Cover request not found.")
        cover = services.accept_cover(cover, tutor)
        return Response(s.CoverRequestSerializer(_cover_qs().get(pk=cover.pk)).data)

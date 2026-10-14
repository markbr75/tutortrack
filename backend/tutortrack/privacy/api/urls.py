from django.urls import path
from rest_framework.routers import SimpleRouter

from .compliance_views import DPAView, MyDataRequestsView, SubprocessorsView
from .dsar_views import (
    DataExportDownloadView,
    DataRequestViewSet,
    ErasurePreviewView,
    ErasureRecordViewSet,
    LegalHoldViewSet,
    RetentionPolicyViewSet,
    RetentionRunViewSet,
)
from .safeguarding_views import (
    ChildPrivacyView,
    ConcernViewSet,
    FlagViewSet,
    RaisedConcernViewSet,
    VisitViewSet,
)
from .views import ConsentRecordViewSet, ConsentTypeViewSet, MyConsentsView

router = SimpleRouter(trailing_slash=False)
router.register("consent-types", ConsentTypeViewSet, basename="consent-types")
router.register("consents", ConsentRecordViewSet, basename="consents")
router.register("data-requests", DataRequestViewSet, basename="data-requests")
router.register("erasures", ErasureRecordViewSet, basename="erasures")
router.register("legal-holds", LegalHoldViewSet, basename="legal-holds")
router.register("retention-policies", RetentionPolicyViewSet, basename="retention-policies")
router.register("retention-runs", RetentionRunViewSet, basename="retention-runs")
router.register("safeguarding/concerns", ConcernViewSet, basename="safeguarding-concerns")
router.register("safeguarding/raised", RaisedConcernViewSet, basename="safeguarding-raised")
router.register("safeguarding/flags", FlagViewSet, basename="safeguarding-flags")
router.register("lone-working/visits", VisitViewSet, basename="lone-working-visits")

urlpatterns = [
    path("me/consents", MyConsentsView.as_view(), name="me-consents"),
    path("me/data-requests", MyDataRequestsView.as_view(), name="me-data-requests"),
    path("erasure-preview", ErasurePreviewView.as_view(), name="erasure-preview"),
    path("data-export/<str:token>", DataExportDownloadView.as_view(), name="data-export"),
    path("dpa", DPAView.as_view(), name="dpa"),
    path("subprocessors", SubprocessorsView.as_view(), name="subprocessors"),
    path(
        "students/<uuid:student_id>/privacy",
        ChildPrivacyView.as_view(),
        name="student-privacy",
    ),
    *router.urls,
]

from django.urls import path, re_path
from rest_framework.routers import SimpleRouter

from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register("shortlists", v.ShortlistViewSet, basename="shortlists")
router.register("job-offer-batches", v.OfferBatchViewSet, basename="job-offer-batches")
router.register("job-postings", v.JobPostingViewSet, basename="job-postings")
router.register("cover-requests", v.CoverRequestViewSet, basename="cover-requests")

urlpatterns = [
    path("matching/search", v.MatchSearchView.as_view(), name="matching-search"),
    path("matching/settings", v.MatchingSettingsView.as_view(), name="matching-settings"),
    path("matching/analytics", v.MatchingAnalyticsView.as_view(), name="matching-analytics"),
    path("job-offers/<uuid:pk>/withdraw", v.JobOfferWithdrawView.as_view(), name="offer-withdraw"),
    path("me/job-offers", v.MyJobOffersView.as_view(), name="my-job-offers"),
    re_path(
        r"^me/job-offers/(?P<pk>[0-9a-f-]{36})/(?P<answer>accept|decline)$",
        v.MyJobOfferAnswerView.as_view(),
        name="my-job-offer-answer",
    ),
    path("me/job-postings", v.MyJobPostingsView.as_view(), name="my-job-postings"),
    path(
        "me/job-postings/<uuid:pk>/apply",
        v.MyJobPostingApplyView.as_view(),
        name="my-job-posting-apply",
    ),
    path("me/cover-requests", v.MyCoverRequestsView.as_view(), name="my-cover-requests"),
    path(
        "me/cover-requests/<uuid:pk>/accept",
        v.MyCoverAcceptView.as_view(),
        name="my-cover-accept",
    ),
    *router.urls,
]

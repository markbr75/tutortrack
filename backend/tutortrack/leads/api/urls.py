from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("pipelines", views.PipelineViewSet, basename="pipelines")
router.register("enquiries", views.EnquiryViewSet, basename="enquiries")
router.register("assignment-rules", views.AssignmentRuleViewSet, basename="assignment-rules")
router.register("forms", views.FormViewSet, basename="forms")
router.register("waitlist", views.WaitlistViewSet, basename="waitlist")
router.register("proposals", views.ProposalViewSet, basename="proposals")

urlpatterns = [
    path("public/forms/<slug:slug>", views.PublicFormView.as_view(), name="public-form"),
    path("public/enquiries", views.PublicEnquiryView.as_view(), name="public-enquiries"),
    path("public/offers/<str:token>", views.PublicOfferView.as_view(), name="public-offer"),
    path(
        "public/proposals/<str:token>", views.PublicProposalView.as_view(), name="public-proposal"
    ),
    path(
        "public/proposals/<str:token>/decline",
        views.PublicProposalDeclineView.as_view(),
        name="public-proposal-decline",
    ),
    path(
        "public/proposals/<str:token>/pdf",
        views.PublicProposalPdfView.as_view(),
        name="public-proposal-pdf",
    ),
    path("leads/reports/funnel", views.FunnelView.as_view(), name="leads-funnel"),
    *router.urls,
]

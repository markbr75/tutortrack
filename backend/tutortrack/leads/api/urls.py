from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("pipelines", views.PipelineViewSet, basename="pipelines")
router.register("enquiries", views.EnquiryViewSet, basename="enquiries")
router.register("assignment-rules", views.AssignmentRuleViewSet, basename="assignment-rules")
router.register("forms", views.FormViewSet, basename="forms")
router.register("waitlist", views.WaitlistViewSet, basename="waitlist")

urlpatterns = [
    path("public/forms/<slug:slug>", views.PublicFormView.as_view(), name="public-form"),
    path("public/enquiries", views.PublicEnquiryView.as_view(), name="public-enquiries"),
    path("public/offers/<str:token>", views.PublicOfferView.as_view(), name="public-offer"),
    path("leads/reports/funnel", views.FunnelView.as_view(), name="leads-funnel"),
    *router.urls,
]

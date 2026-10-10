from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register("job-openings", v.JobOpeningViewSet, basename="job-openings")
router.register("application-stages", v.ApplicationStageViewSet, basename="application-stages")
router.register("applications", v.ApplicationViewSet, basename="applications")
router.register("checklist-templates", v.ChecklistTemplateViewSet, basename="checklist-templates")
router.register(
    "compliance/requirement-types", v.RequirementTypeViewSet, basename="requirement-types"
)

urlpatterns = [
    path("tutors/<uuid:pk>/onboarding", v.TutorOnboardingView.as_view(), name="tutor-onboarding"),
    path(
        "tutors/<uuid:pk>/onboarding/<slug:key>/done",
        v.TutorOnboardingItemView.as_view(),
        name="tutor-onboarding-item",
    ),
    path("tutors/<uuid:pk>/compliance", v.TutorComplianceView.as_view(), name="tutor-compliance"),
    path(
        "tutors/<uuid:pk>/subjects/<uuid:subject_id>/assess",
        v.AssessSubjectView.as_view(),
        name="tutor-subject-assess",
    ),
    path("me/onboarding", v.MyOnboardingView.as_view(), name="my-onboarding"),
    path(
        "me/onboarding/<slug:key>/done", v.MyOnboardingItemView.as_view(), name="my-onboarding-item"
    ),
    path("me/compliance", v.MyComplianceView.as_view(), name="my-compliance"),
    path(
        "compliance/records/<uuid:pk>/verify",
        v.RecordVerifyView.as_view(),
        name="compliance-verify",
    ),
    path(
        "compliance/records/<uuid:pk>/reject",
        v.RecordRejectView.as_view(),
        name="compliance-reject",
    ),
    path("compliance/dashboard", v.DashboardView.as_view(), name="compliance-dashboard"),
    path("public/job-openings", v.PublicOpeningsView.as_view(), name="public-openings"),
    path("public/job-openings/<slug:slug>", v.PublicOpeningView.as_view(), name="public-opening"),
    path("public/interviews/<str:token>", v.PublicInterviewView.as_view(), name="public-interview"),
    path("public/references/<str:token>", v.PublicReferenceView.as_view(), name="public-reference"),
    *router.urls,
]

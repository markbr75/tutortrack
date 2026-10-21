from django.urls import path
from rest_framework.routers import SimpleRouter

from . import check_views as cv
from . import performance_views as pv
from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register("job-openings", v.JobOpeningViewSet, basename="job-openings")
router.register("application-stages", v.ApplicationStageViewSet, basename="application-stages")
router.register("applications", v.ApplicationViewSet, basename="applications")
router.register("checklist-templates", v.ChecklistTemplateViewSet, basename="checklist-templates")
router.register("background-checks", cv.BackgroundCheckViewSet, basename="background-checks")
router.register(
    "compliance/requirement-types", v.RequirementTypeViewSet, basename="requirement-types"
)
router.register("probation-reviews", pv.ProbationReviewViewSet, basename="probation-reviews")
router.register("performance-notes", pv.PerformanceNoteViewSet, basename="performance-notes")

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
    path(
        "me/onboarding/<slug:key>/sign", v.MyOnboardingSignView.as_view(), name="my-onboarding-sign"
    ),
    path("me/compliance", v.MyComplianceView.as_view(), name="my-compliance"),
    path("me/background-checks", cv.MyBackgroundChecksView.as_view(), name="my-background-checks"),
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
    # Gap batch G5a.
    path(
        "compliance/dashboard/export",
        pv.DashboardExportView.as_view(),
        name="compliance-dashboard-export",
    ),
    path(
        "compliance/request-missing",
        pv.RequestMissingView.as_view(),
        name="compliance-request-missing",
    ),
    path("tutors/<uuid:pk>/offboarding", pv.TutorOffboardingView.as_view(), name="offboarding"),
    path(
        "tutors/<uuid:pk>/offboarding/revoke-access",
        pv.TutorRevokeAccessView.as_view(),
        name="offboarding-revoke-access",
    ),
    path(
        "tutors/<uuid:pk>/offboarding/complete",
        pv.TutorCompleteOffboardingView.as_view(),
        name="offboarding-complete",
    ),
    path(
        "tutors/<uuid:pk>/offboarding/<slug:key>/done",
        pv.TutorOffboardingItemView.as_view(),
        name="offboarding-item",
    ),
    path(
        "tutors/<uuid:pk>/subject-tests",
        pv.TutorSubjectTestsView.as_view(),
        name="tutor-subject-tests",
    ),
    path("me/subject-tests", pv.MySubjectTestsView.as_view(), name="my-subject-tests"),
    path(
        "me/subject-tests/<uuid:quiz_id>",
        pv.MySubjectTestView.as_view(),
        name="my-subject-test",
    ),
    path("public/job-openings", v.PublicOpeningsView.as_view(), name="public-openings"),
    path("public/job-openings/<slug:slug>", v.PublicOpeningView.as_view(), name="public-opening"),
    path("public/interviews/<str:token>", v.PublicInterviewView.as_view(), name="public-interview"),
    path("public/references/<str:token>", v.PublicReferenceView.as_view(), name="public-reference"),
    *router.urls,
]

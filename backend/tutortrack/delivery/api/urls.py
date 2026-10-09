from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register(
    "cancellation-policies", views.CancellationPolicyViewSet, basename="cancellation-policies"
)
router.register("report-templates", views.ReportTemplateViewSet, basename="report-templates")
router.register("lesson-reports", views.LessonReportViewSet, basename="lesson-reports")
router.register("makeup-credits", views.MakeupCreditViewSet, basename="makeup-credits")

urlpatterns = [
    path(
        "lessons/<uuid:lesson_id>/reports",
        views.LessonReportsView.as_view(),
        name="lesson-reports-for-lesson",
    ),
    path("unconfirmed-lessons", views.UnconfirmedLessonsView.as_view(), name="unconfirmed-lessons"),
    path(
        "students/<uuid:student_id>/attendance",
        views.AttendanceStatsView.as_view(),
        name="student-attendance",
    ),
    *router.urls,
]

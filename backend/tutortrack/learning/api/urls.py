from django.urls import path
from rest_framework.routers import SimpleRouter

from . import portal_views as pv
from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register("learning/folders", v.FolderViewSet, basename="learning-folders")
router.register("learning/resources", v.ResourceViewSet, basename="learning-resources")
router.register("learning/resource-shares", v.ShareViewSet, basename="learning-resource-shares")
router.register("learning/grade-scales", v.GradeScaleViewSet, basename="learning-grade-scales")
router.register("learning/homework", v.HomeworkViewSet, basename="learning-homework")
router.register(
    "learning/homework-assignments", v.AssignmentViewSet, basename="learning-assignments"
)
router.register("learning/curricula", v.CurriculumViewSet, basename="learning-curricula")
router.register("learning/curriculum-nodes", v.NodeViewSet, basename="learning-nodes")
router.register("learning/lesson-topics", v.LessonTopicViewSet, basename="learning-lesson-topics")
router.register("learning/mastery", v.MasteryViewSet, basename="learning-mastery")
router.register("learning/goals", v.GoalViewSet, basename="learning-goals")
router.register("learning/assessments", v.AssessmentViewSet, basename="learning-assessments")
router.register("learning/assessment-results", v.ResultViewSet, basename="learning-results")
router.register(
    "learning/progress-reports", v.ProgressReportViewSet, basename="learning-progress-reports"
)
router.register("learning/library-items", v.LibraryItemViewSet, basename="learning-items")
router.register("learning/loans", v.LoanViewSet, basename="learning-loans")
router.register("learning/quizzes", v.QuizViewSet, basename="learning-quizzes")
router.register("learning/quiz-attempts", v.QuizAttemptViewSet, basename="learning-attempts")

urlpatterns = [
    path("learning/storage", v.StorageView.as_view(), name="learning-storage"),
    path("learning/topics", v.TopicSuggestionsView.as_view(), name="learning-topics"),
    path(
        "learning/students/<uuid:student_id>/coverage",
        v.CoverageView.as_view(),
        name="learning-coverage",
    ),
    path("learning/students/<uuid:student_id>/trend", v.TrendView.as_view(), name="learning-trend"),
    path("portal/learning/summary", pv.PortalSummaryView.as_view(), name="portal-learning"),
    path("portal/learning/homework", pv.PortalHomeworkView.as_view(), name="portal-homework"),
    path(
        "portal/learning/homework/<uuid:assignment_id>",
        pv.PortalHomeworkDetailView.as_view(),
        name="portal-homework-detail",
    ),
    path(
        "portal/learning/homework/<uuid:assignment_id>/submit",
        pv.PortalHomeworkSubmitView.as_view(),
        name="portal-homework-submit",
    ),
    path("portal/learning/resources", pv.PortalResourcesView.as_view(), name="portal-resources"),
    path(
        "portal/learning/resources/<uuid:resource_id>/open",
        pv.PortalResourceOpenView.as_view(),
        name="portal-resource-open",
    ),
    path("portal/learning/goals", pv.PortalGoalsView.as_view(), name="portal-goals"),
    path("portal/learning/results", pv.PortalResultsView.as_view(), name="portal-results"),
    path(
        "portal/learning/coverage/<uuid:student_id>",
        pv.PortalCoverageView.as_view(),
        name="portal-coverage",
    ),
    path(
        "portal/learning/progress-reports",
        pv.PortalReportsView.as_view(),
        name="portal-progress-reports",
    ),
    path(
        "portal/learning/progress-reports/<uuid:report_id>/pdf",
        pv.PortalReportPdfView.as_view(),
        name="portal-progress-report-pdf",
    ),
    path("portal/learning/loans", pv.PortalLoansView.as_view(), name="portal-loans"),
    *router.urls,
]

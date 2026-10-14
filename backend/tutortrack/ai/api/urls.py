from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register("ai/requests", v.AIRequestLogViewSet, basename="ai-requests")
router.register("ai/assists", v.AIAssistViewSet, basename="ai-assists")
router.register("ai/proposals", v.AIProposalViewSet, basename="ai-proposals")
router.register("ai/thread-insights", v.AIThreadInsightViewSet, basename="ai-thread-insights")

urlpatterns = [
    path("ai/status", v.AIStatusView.as_view(), name="ai-status"),
    path("ai/features", v.AIFeatureListView.as_view(), name="ai-features"),
    path("ai/features/<str:feature>", v.AIFeatureDetailView.as_view(), name="ai-feature"),
    path("ai/usage", v.AIUsageView.as_view(), name="ai-usage"),
    path("ai/feedback", v.AIFeedbackView.as_view(), name="ai-feedback"),
    path(
        "ai/lesson-reports/<uuid:report_id>/draft",
        v.AILessonReportDraftView.as_view(),
        name="ai-lesson-report-draft",
    ),
    path(
        "ai/progress-reports/<uuid:report_id>/draft",
        v.AIProgressDraftView.as_view(),
        name="ai-progress-draft",
    ),
    path("ai/rewrite", v.AIRewriteView.as_view(), name="ai-rewrite"),
    path("ai/enquiries/extract", v.AIEnquiryExtractView.as_view(), name="ai-enquiry-extract"),
    path(
        "ai/enquiries/<uuid:enquiry_id>/triage",
        v.AIEnquiryTriageView.as_view(),
        name="ai-enquiry-triage",
    ),
    path("ai/threads/<uuid:thread_id>/reply", v.AIThreadReplyView.as_view(), name="ai-reply"),
    path("ai/threads/<uuid:thread_id>/summary", v.AIThreadSummaryView.as_view(), name="ai-summary"),
    path(
        "ai/threads/<uuid:thread_id>/classify",
        v.AIThreadClassifyView.as_view(),
        name="ai-classify",
    ),
    path("ai/command", v.AICommandView.as_view(), name="ai-command"),
    path("ai/copilot", v.AICopilotView.as_view(), name="ai-copilot"),
    path("ai/content", v.AIContentView.as_view(), name="ai-content"),
    path("ai/matching/explain", v.AIMatchExplainView.as_view(), name="ai-match-explain"),
    *router.urls,
]

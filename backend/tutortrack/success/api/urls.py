from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register(
    "support-conversations", v.SupportConversationViewSet, basename="support-conversations"
)

urlpatterns = [
    path("help/articles", v.HelpArticlesView.as_view(), name="help-articles"),
    path("help/articles/<slug:slug>", v.HelpArticleView.as_view(), name="help-article"),
    path("help/changelog", v.ChangelogView.as_view(), name="help-changelog"),
    path("help/changelog/seen", v.ChangelogSeenView.as_view(), name="help-changelog-seen"),
    path("me/guidance", v.GuidanceView.as_view(), name="me-guidance"),
    path("me/guidance/tours/<slug:key>", v.TourView.as_view(), name="me-guidance-tour"),
    path("setup-checklist", v.SetupChecklistView.as_view(), name="setup-checklist"),
    path("surveys/responses", v.SurveyResponsesView.as_view(), name="survey-responses"),
    path("analytics/events", v.ProductEventsView.as_view(), name="product-events"),
    *router.urls,
]

from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("messages", views.MessageViewSet, basename="messages")
router.register("notifications", views.NotificationViewSet, basename="notifications")

urlpatterns = [
    path(
        "notification-settings",
        views.NotificationSettingsView.as_view(),
        name="notification-settings",
    ),
    path(
        "notification-settings/<slug:key>",
        views.NotificationSettingView.as_view(),
        name="notification-setting",
    ),
    path(
        "message-templates/<slug:key>/<slug:channel>",
        views.TemplateView.as_view(),
        name="message-template",
    ),
    path(
        "message-templates/<slug:key>/<slug:channel>/preview",
        views.TemplatePreviewView.as_view(),
        name="message-template-preview",
    ),
    path(
        "message-templates/<slug:key>/<slug:channel>/test",
        views.TemplateTestView.as_view(),
        name="message-template-test",
    ),
    path(
        "communication-preferences",
        views.PreferencesView.as_view(),
        name="communication-preferences",
    ),
    path("unsubscribe/<str:token>", views.UnsubscribeView.as_view(), name="unsubscribe"),
    *router.urls,
]

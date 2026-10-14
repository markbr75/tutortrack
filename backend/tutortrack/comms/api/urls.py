from django.urls import path
from rest_framework.routers import SimpleRouter

from . import phase2_views as p2
from . import views

router = SimpleRouter(trailing_slash=False)
# Phase 2 (E13-T10..T12)
router.register("segments", p2.SegmentViewSet, basename="segments")
router.register("broadcasts", p2.BroadcastViewSet, basename="broadcasts")
router.register("threads", p2.ThreadViewSet, basename="threads")
router.register("canned-replies", p2.CannedReplyViewSet, basename="canned-replies")
router.register("sender-domains", p2.SenderDomainViewSet, basename="sender-domains")
router.register("phone-numbers", p2.PhoneNumberViewSet, basename="phone-numbers")
router.register("whatsapp-templates", p2.WhatsAppTemplateViewSet, basename="whatsapp-templates")
router.register("messages", views.MessageViewSet, basename="messages")
router.register("notifications", views.NotificationViewSet, basename="notifications")
router.register("push-subscriptions", views.PushSubscriptionViewSet, basename="push-subscriptions")

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
    path(
        "communication-preferences/mine",
        views.MyPreferencesView.as_view(),
        name="my-communication-preferences",
    ),
    path("unsubscribe/<str:token>", views.UnsubscribeView.as_view(), name="unsubscribe"),
    path("marketing-sync", p2.MarketingSyncView.as_view(), name="marketing-sync"),
    path(
        "marketing-sync/<slug:provider>/audiences",
        p2.MarketingAudienceView.as_view(),
        name="marketing-sync-audiences",
    ),
    path(
        "marketing-sync/<slug:provider>/sync",
        p2.MarketingSyncNowView.as_view(),
        name="marketing-sync-now",
    ),
    *router.urls,
]

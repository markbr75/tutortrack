from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register("calendar-sync/busy-blocks", v.BusyBlockViewSet, basename="busy-blocks")
router.register("online-meetings", v.OnlineMeetingViewSet, basename="online-meetings")

urlpatterns = [
    path(
        "calendar-sync/connections/<uuid:pk>/settings",
        v.CalendarSyncSettingsView.as_view(),
        name="calendar-sync-settings",
    ),
    path(
        "calendar-sync/connections/<uuid:pk>/sync",
        v.CalendarSyncNowView.as_view(),
        name="calendar-sync-now",
    ),
    path("online-meetings/provision", v.ProvisionMeetingView.as_view(), name="meeting-provision"),
    path("me/meeting-preference", v.MeetingPreferenceView.as_view(), name="meeting-preference"),
    path("lessons/<uuid:pk>/join", v.LessonJoinView.as_view(), name="lesson-join"),
    *router.urls,
]

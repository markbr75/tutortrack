from django.urls import path
from rest_framework.routers import SimpleRouter

from . import video_views as vv
from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register("calendar-sync/busy-blocks", v.BusyBlockViewSet, basename="busy-blocks")
router.register("online-meetings", v.OnlineMeetingViewSet, basename="online-meetings")
router.register("recordings", vv.LessonRecordingViewSet, basename="recordings")

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
    # E22-T10: video attendance, recordings and the classroom
    path(
        "lessons/<uuid:pk>/video-attendance",
        vv.VideoAttendanceView.as_view(),
        name="lesson-video-attendance",
    ),
    path("lessons/<uuid:pk>/classroom", vv.ClassroomView.as_view(), name="lesson-classroom"),
    path(
        "lessons/<uuid:pk>/classroom/consent",
        vv.ClassroomConsentView.as_view(),
        name="lesson-classroom-consent",
    ),
    path(  # gap G5c (FR-21-8): open a resource shared into the classroom
        "lessons/<uuid:pk>/classroom/resources/<uuid:resource_id>/open",
        vv.ClassroomResourceOpenView.as_view(),
        name="lesson-classroom-resource-open",
    ),
    path("recordings/<uuid:pk>/play", vv.RecordingPlayView.as_view(), name="recording-play"),
    path("me/recordings", vv.MyRecordingsView.as_view(), name="my-recordings"),
    *router.urls,
]

from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("lessons", views.LessonViewSet, basename="lessons")
router.register("lesson-series", views.SeriesViewSet, basename="lesson-series")
router.register("events", views.EventViewSet, basename="events")
router.register("time-off", views.TimeOffViewSet, basename="time-off")
router.register("ical-feeds", views.FeedViewSet, basename="ical-feeds")

urlpatterns = [
    path("calendar", views.CalendarView.as_view(), name="calendar"),
    path("conflicts/check", views.ConflictCheckView.as_view(), name="conflicts-check"),
    path("availability/<uuid:tutor_id>", views.AvailabilityView.as_view(), name="availability"),
    path(
        "availability/<uuid:tutor_id>/slots", views.SlotsView.as_view(), name="availability-slots"
    ),
    *router.urls,
]

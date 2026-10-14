from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("lessons", views.LessonViewSet, basename="lessons")
router.register("lesson-series", views.SeriesViewSet, basename="lesson-series")
router.register("events", views.EventViewSet, basename="events")
router.register("time-off", views.TimeOffViewSet, basename="time-off")
router.register("ical-feeds", views.FeedViewSet, basename="ical-feeds")
router.register(
    "reschedule-requests", views.RescheduleRequestViewSet, basename="reschedule-requests"
)
router.register("booking/holds", views.BookingHoldViewSet, basename="booking-holds")

urlpatterns = [
    path("calendar", views.CalendarView.as_view(), name="calendar"),
    path("calendar/rooms", views.RoomScheduleView.as_view(), name="calendar-rooms"),
    path("calendar/timetable", views.TimetableView.as_view(), name="calendar-timetable"),
    path("lessons/reprice", views.RepriceView.as_view(), name="lessons-reprice"),
    path(
        "lessons/<uuid:lesson_id>/reschedule-requests",
        views.LessonRescheduleRequestView.as_view(),
        name="lesson-reschedule-requests",
    ),
    path("booking/settings", views.BookingSettingsView.as_view(), name="booking-settings"),
    path(
        "public/booking/services",
        views.PublicBookingServicesView.as_view(),
        name="public-booking-services",
    ),
    path(
        "public/booking/slots", views.PublicBookingSlotsView.as_view(), name="public-booking-slots"
    ),
    path(
        "public/booking/holds", views.PublicBookingHoldsView.as_view(), name="public-booking-holds"
    ),
    path(
        "public/booking/holds/<uuid:hold_id>",
        views.PublicBookingHoldView.as_view(),
        name="public-booking-hold",
    ),
    path(
        "public/booking/holds/<uuid:hold_id>/submit",
        views.PublicBookingSubmitView.as_view(),
        name="public-booking-submit",
    ),
    path(
        "public/booking/holds/<uuid:hold_id>/cancel",
        views.PublicBookingCancelView.as_view(),
        name="public-booking-cancel",
    ),
    path("conflicts/check", views.ConflictCheckView.as_view(), name="conflicts-check"),
    path("availability/<uuid:tutor_id>", views.AvailabilityView.as_view(), name="availability"),
    path(
        "availability/<uuid:tutor_id>/slots", views.SlotsView.as_view(), name="availability-slots"
    ),
    *router.urls,
]

from django.urls import path
from rest_framework.routers import SimpleRouter

from . import booking_views as bv
from . import tutor_views, views

router = SimpleRouter(trailing_slash=False)
router.register("announcements", views.AnnouncementViewSet, basename="announcements")

urlpatterns = [
    path("portal/me", views.MeView.as_view(), name="portal-me"),
    path("portal/dashboard", views.DashboardView.as_view(), name="portal-dashboard"),
    path("portal/schedule", views.ScheduleView.as_view(), name="portal-schedule"),
    path("portal/lessons/<uuid:lesson_id>/ics", views.LessonIcsView.as_view(), name="portal-ics"),
    path(
        "portal/lessons/<uuid:lesson_id>/cancel",
        views.CancelView.as_view(),
        name="portal-cancel",
    ),
    path(
        "portal/lessons/<uuid:lesson_id>/absence",
        views.AbsenceView.as_view(),
        name="portal-absence",
    ),
    path(
        "portal/lessons/<uuid:lesson_id>/reschedule",
        bv.PortalLessonRescheduleView.as_view(),
        name="portal-reschedule",
    ),
    path(
        "portal/reschedule-requests",
        bv.PortalRescheduleRequestsView.as_view(),
        name="portal-reschedule-requests",
    ),
    path(
        "portal/reschedule-requests/<uuid:request_id>/decide",
        bv.PortalRescheduleDecideView.as_view(),
        name="portal-reschedule-decide",
    ),
    path(
        "portal/reschedule-requests/<uuid:request_id>/cancel",
        bv.PortalRescheduleCancelView.as_view(),
        name="portal-reschedule-cancel",
    ),
    path(
        "portal/booking/services",
        bv.PortalBookingServicesView.as_view(),
        name="portal-booking-services",
    ),
    path("portal/booking/slots", bv.PortalBookingSlotsView.as_view(), name="portal-booking-slots"),
    path("portal/booking/holds", bv.PortalBookingHoldsView.as_view(), name="portal-booking-holds"),
    path(
        "portal/booking/holds/<uuid:hold_id>/submit",
        bv.PortalBookingSubmitView.as_view(),
        name="portal-booking-submit",
    ),
    path(
        "portal/booking/holds/<uuid:hold_id>/cancel",
        bv.PortalBookingCancelView.as_view(),
        name="portal-booking-cancel",
    ),
    path("portal/reports", views.ReportsView.as_view(), name="portal-reports"),
    path(
        "portal/reports/<uuid:report_id>/comments",
        views.ReportCommentView.as_view(),
        name="portal-report-comments",
    ),
    path("portal/billing", views.BillingView.as_view(), name="portal-billing"),
    path("portal/statement", views.StatementView.as_view(), name="portal-statement"),
    path("portal/packages", views.BuyPackageView.as_view(), name="portal-buy-package"),
    path("portal/payment-methods", views.PaymentMethodsView.as_view(), name="portal-methods"),
    path("portal/profile", views.ProfileView.as_view(), name="portal-profile"),
    path(
        "portal/profile/contacts/<uuid:contact_id>",
        views.ContactProfileView.as_view(),
        name="portal-contact",
    ),
    path(
        "portal/profile/students/<uuid:student_id>",
        views.StudentProfileView.as_view(),
        name="portal-student",
    ),
    path(
        "portal/announcements",
        views.PortalAnnouncementsView.as_view(),
        name="portal-announcements",
    ),
    path("tutor/me", tutor_views.TutorMeView.as_view(), name="tutor-me"),
    path("tutor/today", tutor_views.TutorTodayView.as_view(), name="tutor-today"),
    path("tutor/offline", tutor_views.TutorOfflineView.as_view(), name="tutor-offline"),
    path("tutor/students", tutor_views.TutorStudentsView.as_view(), name="tutor-students"),
    path("tutor/earnings", tutor_views.TutorEarningsView.as_view(), name="tutor-earnings"),
    path(
        "<str:kind>/<uuid:record_id>/portal-invite",
        views.InviteView.as_view(),
        name="portal-invite",
    ),
    *router.urls,
]

from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

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
    path("portal/reports", views.ReportsView.as_view(), name="portal-reports"),
    path(
        "portal/reports/<uuid:report_id>/comments",
        views.ReportCommentView.as_view(),
        name="portal-report-comments",
    ),
    path("portal/billing", views.BillingView.as_view(), name="portal-billing"),
    path("portal/statement", views.StatementView.as_view(), name="portal-statement"),
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
    path(
        "<str:kind>/<uuid:record_id>/portal-invite",
        views.InviteView.as_view(),
        name="portal-invite",
    ),
    *router.urls,
]

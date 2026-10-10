from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register("saved-reports", v.SavedReportViewSet, basename="saved-reports")
router.register("scheduled-reports", v.ScheduledReportViewSet, basename="scheduled-reports")
router.register("report-runs", v.ReportRunViewSet, basename="report-runs")

urlpatterns = [
    path("reporting/reports", v.ReportListView.as_view(), name="reporting-reports"),
    path("reporting/reports/<slug:key>", v.ReportRunView.as_view(), name="reporting-report"),
    path(
        "reporting/reports/<slug:key>/export",
        v.ReportExportView.as_view(),
        name="reporting-report-export",
    ),
    path("reporting/dashboard", v.DashboardView.as_view(), name="reporting-dashboard"),
    path("reporting/widgets", v.WidgetListView.as_view(), name="reporting-widgets"),
    path("reporting/widgets/<slug:key>", v.WidgetDataView.as_view(), name="reporting-widget"),
    path("reporting/rebuild", v.RebuildView.as_view(), name="reporting-rebuild"),
    *router.urls,
]

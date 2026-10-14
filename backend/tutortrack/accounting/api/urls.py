from django.urls import path
from rest_framework.routers import SimpleRouter

from . import payroll_views as pv
from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register(
    "accounting/connections", v.AccountingConnectionViewSet, basename="accounting-connections"
)
router.register("accounting/records", v.ExternalRecordViewSet, basename="accounting-records")
router.register(
    "accounting/payment-imports",
    v.LedgerPaymentImportViewSet,
    basename="accounting-payment-imports",
)
router.register(
    "accounting/xero-payroll/syncs", pv.PayrollTimesheetSyncViewSet, basename="xero-payroll-syncs"
)

urlpatterns = [
    path(
        "accounting/mappings/<str:provider>",
        v.MappingSetView.as_view(),
        name="accounting-mappings",
    ),
    path("accounting/export", v.ExportView.as_view(), name="accounting-export"),
    # E23-T10: Xero Payroll
    path("accounting/xero-payroll", pv.XeroPayrollView.as_view(), name="xero-payroll"),
    path(
        "accounting/xero-payroll/match",
        pv.XeroPayrollMatchView.as_view(),
        name="xero-payroll-match",
    ),
    path(
        "accounting/xero-payroll/links", pv.XeroPayrollLinkView.as_view(), name="xero-payroll-links"
    ),
    path(
        "accounting/xero-payroll/employees",
        pv.XeroPayrollEmployeesView.as_view(),
        name="xero-payroll-employees",
    ),
    path(
        "accounting/xero-payroll/earnings-rate",
        pv.XeroPayrollEarningsRateView.as_view(),
        name="xero-payroll-earnings-rate",
    ),
    path(
        "accounting/xero-payroll/sync", pv.XeroPayrollSyncView.as_view(), name="xero-payroll-sync"
    ),
    *router.urls,
]

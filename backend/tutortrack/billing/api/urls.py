from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("charges", views.ChargeViewSet, basename="charges")
router.register("invoices", views.InvoiceViewSet, basename="invoices")
router.register("credit-notes", views.CreditNoteViewSet, basename="credit-notes")
router.register("invoice-runs", views.InvoiceRunViewSet, basename="invoice-runs")
router.register("payment-requests", views.PaymentRequestViewSet, basename="payment-requests")
router.register("packages", views.PackageViewSet, basename="package-purchases")
router.register("billing-plans", views.BillingPlanViewSet, basename="billing-plans")
router.register("billing/late-fee-rules", views.LateFeeRuleViewSet, basename="late-fee-rules")
router.register("invoice-templates", views.InvoiceTemplateViewSet, basename="invoice-templates")
router.register("billing/collections", views.CollectionsCaseViewSet, basename="collections")
router.register("me/invoice-reviews", views.MyInvoiceReviewViewSet, basename="my-invoice-reviews")

urlpatterns = [
    path(
        "charges/<uuid:charge_id>/waive",
        views.WaiveLateFeeView.as_view(),
        name="charge-waive",
    ),
    path("billing/splits", views.BillingSplitView.as_view(), name="billing-splits"),
    path(
        "clients/<uuid:client_id>/balance", views.ClientBalanceView.as_view(), name="client-balance"
    ),
    path("clients/<uuid:client_id>/ledger", views.ClientLedgerView.as_view(), name="client-ledger"),
    path(
        "clients/<uuid:client_id>/statement",
        views.ClientStatementView.as_view(),
        name="client-statement",
    ),
    path("billing/ageing", views.AgeingView.as_view(), name="billing-ageing"),
    *router.urls,
]

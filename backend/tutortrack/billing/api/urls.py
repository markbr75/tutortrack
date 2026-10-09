from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("charges", views.ChargeViewSet, basename="charges")
router.register("invoices", views.InvoiceViewSet, basename="invoices")
router.register("credit-notes", views.CreditNoteViewSet, basename="credit-notes")
router.register("invoice-runs", views.InvoiceRunViewSet, basename="invoice-runs")
router.register("payment-requests", views.PaymentRequestViewSet, basename="payment-requests")

urlpatterns = [
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

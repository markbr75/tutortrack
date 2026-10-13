from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("payments/providers", views.ProviderAccountViewSet, basename="payment-providers")
router.register("payments/disputes", views.DisputeViewSet, basename="payment-disputes")
router.register("payments/payouts", views.PayoutViewSet, basename="payment-payouts")
router.register("payment-methods", views.PaymentMethodViewSet, basename="payment-methods")
router.register(
    "payments/provider-migrations",
    views.ProviderMigrationViewSet,
    basename="provider-migrations",
)
router.register("bank-reconciliation/imports", views.BankImportViewSet, basename="bank-imports")
router.register(
    "bank-reconciliation/transactions",
    views.BankTransactionViewSet,
    basename="bank-transactions",
)
router.register("payments", views.PaymentViewSet, basename="payments")

urlpatterns = [
    path("payments/split", views.SplitPaymentView.as_view(), name="payments-split"),
    path(
        "clients/<uuid:client_id>/provider-migration",
        views.ClientMigrationView.as_view(),
        name="client-provider-migration",
    ),
    path(
        "clients/<uuid:client_id>/payment-methods",
        views.ClientMethodsView.as_view(),
        name="client-payment-methods",
    ),
    path(
        "clients/<uuid:client_id>/payment-methods/setup-link",
        views.ClientSetupLinkView.as_view(),
        name="client-payment-setup-link",
    ),
    path(
        "clients/<uuid:client_id>/autopay",
        views.ClientAutoPayView.as_view(),
        name="client-autopay",
    ),
    path(
        "invoices/<uuid:invoice_id>/collect",
        views.InvoiceCollectView.as_view(),
        name="invoice-collect",
    ),
    path("pay/setup/<str:token>", views.PublicSetupView.as_view(), name="pay-setup"),
    path("pay/<str:token>", views.PublicPayView.as_view(), name="pay-page"),
    path("pay/<str:token>/intent", views.PublicPayIntentView.as_view(), name="pay-intent"),
    path("pay/<str:token>/confirm", views.PublicPayConfirmView.as_view(), name="pay-confirm"),
    path("pay/<str:token>/pdf", views.PublicPayPdfView.as_view(), name="pay-pdf"),
    *router.urls,
]

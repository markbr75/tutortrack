from django.urls import path

from . import views

urlpatterns = [
    path("subscription", views.SubscriptionView.as_view(), name="subscription"),
    path("subscription/plans", views.PlansView.as_view(), name="subscription-plans"),
    path("subscription/checkout-session", views.CheckoutView.as_view(),
         name="subscription-checkout"),
    path("subscription/checkout-session/complete", views.CompleteCheckoutView.as_view(),
         name="subscription-checkout-complete"),
    path("subscription/portal-session", views.PortalView.as_view(), name="subscription-portal"),
    path("subscription/change-plan", views.ChangePlanView.as_view(),
         name="subscription-change-plan"),
    path("subscription/cancel", views.CancelView.as_view(), name="subscription-cancel"),
    path("subscription/reactivate", views.ReactivateView.as_view(),
         name="subscription-reactivate"),
    path("subscription/usage", views.UsageView.as_view(), name="subscription-usage"),
    path("subscription/invoices", views.InvoicesView.as_view(), name="subscription-invoices"),
    path("subscription/credits/<str:credit_type>", views.CreditsView.as_view(),
         name="subscription-credits"),
    path("subscription/credits/<str:credit_type>/top-up", views.TopUpView.as_view(),
         name="subscription-top-up"),
    path("entitlements", views.EntitlementsView.as_view(), name="entitlements"),
]  # fmt: skip

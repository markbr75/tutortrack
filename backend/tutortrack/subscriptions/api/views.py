"""Billing & plan API for our own subscription (E04 §4) and the Stripe Billing webhook.

Paths live under ``/api/v1/subscription`` so they stay writable while the organisation is
suspended (``SUSPENDED_ORG_WRITE_ALLOWLIST``): the owner can always pay to reactivate.
"""

from __future__ import annotations

from typing import Any

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, has_perm

from .. import credits, entitlements, selectors, services
from ..catalogue import FEATURES, LIMITS
from ..gateway import GatewayError, get_gateway
from ..models import CreditType, Plan, PlanPrice, Subscription
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]
VIEW, MANAGE = "subscription.view", "subscription.manage"


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


def _money(value: Any) -> dict[str, str] | None:
    return value.to_dict() if value is not None else None


def _card(subscription: Subscription) -> dict[str, Any] | None:
    if not subscription.stripe_customer_id:
        return None
    key = f"sub-card:{subscription.stripe_customer_id}"
    cached = cache.get(key)
    if cached is None:
        try:
            card = get_gateway().default_card(subscription.stripe_customer_id)
        except GatewayError:
            return None
        cached = card.__dict__ if card else {}
        cache.set(key, cached, 300)
    return cached or None


def _subscription_out(request: Request, subscription: Subscription) -> dict[str, Any]:
    return s.SubscriptionSerializer(
        {
            "plan": subscription.plan,
            "effective_plan": entitlements.effective_plan_key(subscription),
            "status": subscription.status,
            "interval": subscription.interval,
            "currency": subscription.currency,
            "trial_ends_at": subscription.trial_ends_at,
            "current_period_end": subscription.current_period_end,
            "pending_plan": subscription.pending_plan,
            "pending_interval": subscription.pending_interval,
            "cancel_at_period_end": subscription.cancel_at_period_end,
            "past_due_since": subscription.past_due_since,
            "has_payment_method": bool(subscription.stripe_subscription_id),
            "card": _card(subscription),
            "can_manage": has_perm(request.user, MANAGE),
        }
    ).data


def _subscription() -> Subscription:
    subscription = services.current()
    if subscription is None:
        raise NotFound("This organisation has no subscription.")
    return subscription


def _account_out(credit_type: str) -> dict[str, Any]:
    return dict(s.CreditAccountSerializer(credits.account(credit_type)).data)


class PlansView(APIView):
    """Public plans with prices in the organisation's billing currency (FR-04-1)."""

    permission_classes = perms({"GET": VIEW})

    @extend_schema(responses=s.PlanSerializer(many=True))
    def get(self, request: Request) -> Response:
        subscription = services.current()
        currency = (
            subscription.currency if subscription else services.currency_for(request.organisation)  # type: ignore[attr-defined]
        )
        plans = Plan.objects.exclude(visibility=Plan.Visibility.LEGACY).prefetch_related(
            "prices", "entitlements"
        )
        out = []
        for plan in plans:
            values = {e.key: e for e in plan.entitlements.all()}
            out.append({
                "key": plan.key, "name": plan.name, "description": plan.description,
                "visibility": plan.visibility, "rank": plan.rank, "currency": currency,
                "prices": [
                    {"interval": p.interval, "component": p.component,
                     "unit_amount": str(p.unit_amount.normalize()),
                     "included_quantity": p.included_quantity}
                    for p in plan.prices.all() if p.currency == currency
                ],
                "features": {k: bool(values[k].bool_value) for k in FEATURES if k in values},
                "limits": {k: values[k].int_value for k in LIMITS if k in values},
            })  # fmt: skip
        return Response(s.PlanSerializer(out, many=True).data)


class SubscriptionView(APIView):
    permission_classes = perms({"GET": VIEW})

    @extend_schema(responses=s.SubscriptionSerializer)
    def get(self, request: Request) -> Response:
        return Response(_subscription_out(request, _subscription()))


class CheckoutView(APIView):
    """Start paying for a plan with Stripe Checkout; the browser goes to ``url``."""

    permission_classes = perms({"POST": MANAGE})

    @extend_schema(
        request=s.PlanChoiceSerializer,
        responses=s.RedirectSerializer,
        examples=[OpenApiExample("Team, annual", value={"plan": "team", "interval": "year"},
                                 request_only=True)],
    )  # fmt: skip
    def post(self, request: Request) -> Response:
        payload = s.PlanChoiceSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        url = services.checkout(payload.validated_data["plan"], payload.validated_data["interval"])
        return Response({"url": url})


class CompleteCheckoutView(APIView):
    """Called when Checkout returns, so the plan shows straight away (the webhook also
    arrives; both are idempotent)."""

    permission_classes = perms({"POST": MANAGE})

    @extend_schema(request=s.CompleteCheckoutSerializer, responses=s.SubscriptionSerializer)
    def post(self, request: Request) -> Response:
        payload = s.CompleteCheckoutSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        subscription = services.complete_checkout(payload.validated_data["session_id"])
        subscription.refresh_from_db()
        return Response(_subscription_out(request, subscription))


class PortalView(APIView):
    """Stripe's customer portal: card, billing details and invoices."""

    permission_classes = perms({"POST": MANAGE})

    @extend_schema(request=None, responses=s.RedirectSerializer)
    def post(self, request: Request) -> Response:
        return Response({"url": services.portal_url()})


class ChangePlanView(APIView):
    permission_classes = perms({"POST": MANAGE})

    @extend_schema(
        request=s.PlanChoiceSerializer,
        parameters=[OpenApiParameter("preview", bool, description="Only preview the change")],
        responses={200: s.SubscriptionSerializer, 202: s.ChangePreviewSerializer},
    )
    def post(self, request: Request) -> Response:
        payload = s.PlanChoiceSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        plan, interval = payload.validated_data["plan"], payload.validated_data["interval"]
        if request.query_params.get("preview") in ("1", "true"):
            preview = services.preview_change(plan, interval)
            data = {**preview.__dict__, "amount_due_now": _money(preview.amount_due_now)}
            return Response(s.ChangePreviewSerializer(data).data, status=202)
        subscription = services.change_plan(plan, interval)
        return Response(_subscription_out(request, subscription))


class CancelView(APIView):
    permission_classes = perms({"POST": MANAGE})

    @extend_schema(request=s.CancelSubscriptionSerializer, responses=s.SubscriptionSerializer)
    def post(self, request: Request) -> Response:
        payload = s.CancelSubscriptionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        subscription = services.cancel(
            payload.validated_data["reason"], payload.validated_data.get("feedback", "")
        )
        return Response(_subscription_out(request, subscription))


class ReactivateView(APIView):
    permission_classes = perms({"POST": MANAGE})

    @extend_schema(request=None, responses=s.ReactivateSerializer)
    def post(self, request: Request) -> Response:
        subscription, url = services.reactivate()
        return Response({"subscription": _subscription_out(request, subscription), "url": url})


class UsageView(APIView):
    """Settings → Billing & plan: limits used, seats, credits, next invoice (FR-04-7)."""

    permission_classes = perms({"GET": VIEW})

    @extend_schema(responses=s.UsageSerializer)
    def get(self, request: Request) -> Response:
        subscription = _subscription()
        counts = selectors.usage_counts()
        counts["storage_gb"] = -(-counts["storage_gb"] // selectors.BYTES_PER_GB)
        snap = entitlements.snapshot() or {"limits": {}}
        limits = [
            {"key": key, "title": str(LIMITS[key]), "used": counts[key],
             "allowed": snap["limits"].get(key)}
            for key in ("max_tutors", "max_active_students", "max_branches", "storage_gb")
        ]  # fmt: skip
        included = PlanPrice.objects.filter(
            plan=subscription.plan, currency=subscription.currency,
            interval=subscription.interval, component=PlanPrice.Component.ACTIVE_TUTOR,
        ).values_list("included_quantity", flat=True).first()  # fmt: skip
        next_invoice = None
        if subscription.stripe_subscription_id:
            try:
                next_invoice = get_gateway().upcoming_total(subscription.stripe_subscription_id)
            except GatewayError:
                next_invoice = None
        return Response(
            s.UsageSerializer(
                {
                    "limits": limits,
                    "billable_tutors": selectors.billable_tutors(subscription),
                    "included_tutors": included or 0,
                    "next_invoice": _money(next_invoice),
                    "credits": [_account_out(t) for t in CreditType.values],
                }
            ).data
        )


class InvoicesView(APIView):
    """Our invoices to the organisation (PDFs hosted by Stripe)."""

    permission_classes = perms({"GET": VIEW})

    @extend_schema(responses=s.InvoiceSummarySerializer(many=True))
    def get(self, request: Request) -> Response:
        subscription = _subscription()
        if not subscription.stripe_customer_id:
            return Response([])
        try:
            invoices = get_gateway().invoices(subscription.stripe_customer_id)
        except GatewayError:
            invoices = []
        return Response(
            s.InvoiceSummarySerializer(
                [{**i.__dict__, "total": i.total.to_dict()} for i in invoices], many=True
            ).data
        )


def _credit_type(value: str) -> str:
    if value not in CreditType.values:
        raise NotFound()
    return value


class CreditsView(APIView):
    permission_classes = perms({"GET": VIEW, "PATCH": MANAGE})

    @extend_schema(responses=s.CreditDetailSerializer)
    def get(self, request: Request, credit_type: str) -> Response:
        _subscription()
        kind = _credit_type(credit_type)
        return Response(
            {
                "account": _account_out(kind),
                "ledger": s.CreditLedgerEntrySerializer(credits.ledger(kind), many=True).data,
            }
        )

    @extend_schema(request=s.CreditSettingsSerializer, responses=s.CreditAccountSerializer)
    def patch(self, request: Request, credit_type: str) -> Response:
        _subscription()
        kind = _credit_type(credit_type)
        payload = s.CreditSettingsSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        credits.update_settings(kind, **payload.validated_data)
        return Response(_account_out(kind))


class TopUpView(APIView):
    """Buy a pack: charged to the saved card, or a Checkout page when there isn't one."""

    permission_classes = perms({"POST": MANAGE})

    @extend_schema(request=s.TopUpSerializer, responses=s.TopUpResultSerializer)
    def post(self, request: Request, credit_type: str) -> Response:
        kind = _credit_type(credit_type)
        payload = s.TopUpSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        _purchase, url = credits.buy(kind, payload.validated_data["credits"])
        return Response(
            {"status": "redirect" if url else "paid", "url": url, "account": _account_out(kind)}
        )


class EntitlementsView(APIView):
    """What the organisation's plan includes, for ``useEntitlement()`` (FR-04-2)."""

    permission_classes = AUTH

    @extend_schema(responses=s.EntitlementsSerializer)
    def get(self, request: Request) -> Response:
        snap = entitlements.snapshot()
        if snap is None:  # not on a subscription: nothing is limited
            snap = {"plan": None, "status": None, "features": dict.fromkeys(FEATURES, True),
                    "limits": dict.fromkeys(LIMITS)}  # fmt: skip
        required = cache.get("ent:required-plans")
        if required is None:
            required = {
                key: entitlements.cheapest_plan_with(key) or "enterprise" for key in FEATURES
            }
            cache.set("ent:required-plans", required, 3600)
        return Response(s.EntitlementsSerializer({**snap, "required_plans": required}).data)


@csrf_exempt
def stripe_billing_webhook(request: HttpRequest) -> HttpResponse:
    """``POST /webhooks/stripe/platform``: Stripe Billing events for our own subscriptions."""
    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        services.ingest_webhook(request.body, request.headers.get("Stripe-Signature", ""))
    except GatewayError:
        return HttpResponse(status=400)
    return HttpResponse(status=200)

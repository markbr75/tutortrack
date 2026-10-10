"""Our own subscription (E04): trials, checkout, plan changes, cancellation, dunning state,
seat and usage reporting, and Stripe Billing webhooks.

The organisation's status follows the subscription: trialing → trial, active → active,
past due → past due, suspended or cancelled → suspended (read-only for owners and admins,
closed to everyone else; ``OrganisationStatusMiddleware``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import structlog
from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id, tenant_context
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, Conflict, NotFound
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.tenancy.models import Organisation

from . import entitlements, events, selectors
from .catalogue import CURRENCIES, LIMITS, sync_plans
from .gateway import GatewayError, Item, RemoteSubscription, get_gateway
from .models import (
    BillingEvent,
    CustomerRoute,
    EntitlementOverride,
    Interval,
    MeterReport,
    Plan,
    PlanPrice,
    Subscription,
)

logger = structlog.get_logger(__name__)

PLAN_PAGE = "/settings/plan"
REVENUE_METER = "tutortrack_revenue"
DEFAULT_PLAN_FOR = {"sole_trader": "solo", "team": "team"}  # anything else: agency


# --- plans and prices ---------------------------------------------------------------------------


def get_plan(key: str) -> Plan:
    plan = Plan.objects.filter(key=key).first()
    if plan is None:
        sync_plans()  # the catalogue is code; heal an empty table (fresh test databases)
        plan = Plan.objects.filter(key=key).first()
    if plan is None:
        raise NotFound(_("Unknown plan."))
    return plan


def price_ref(price: PlanPrice) -> str:
    """The Stripe price id, or a stable stand-in for the fake gateway."""
    return price.stripe_price_id or (
        f"tt:{price.plan.key}:{price.currency}:{price.interval}:{price.component}"
    )


def price_for_ref(ref: str) -> PlanPrice | None:
    price = PlanPrice.objects.select_related("plan").filter(stripe_price_id=ref).first()
    if price is not None or not ref.startswith("tt:"):
        return price
    _tt, plan, currency, interval, component = (ref.split(":") + [""] * 5)[:5]
    return (
        PlanPrice.objects.select_related("plan")
        .filter(plan__key=plan, currency=currency, interval=interval, component=component)
        .first()
    )


def plan_prices(plan: Plan, currency: str, interval: str) -> list[PlanPrice]:
    return list(
        PlanPrice.objects.select_related("plan").filter(
            plan=plan, currency=currency, interval=interval
        )
    )


def currency_for(organisation: Organisation) -> str:
    return organisation.default_currency if organisation.default_currency in CURRENCIES else "USD"


def items_for(subscription: Subscription, plan: Plan, interval: str) -> list[Item]:
    prices = plan_prices(plan, subscription.currency, interval)
    if not prices:
        raise BusinessRuleViolation(
            _("This plan isn't available to buy online in your currency. Contact us to set it up."),
            extra={"code": "contact_sales"},
        )
    seats = selectors.billable_tutors(subscription)
    branches = selectors.branch_count()
    items = []
    for price in prices:
        if price.component == PlanPrice.Component.REVENUE_SHARE:
            items.append(Item(price_ref(price), None))
        elif price.component == PlanPrice.Component.ACTIVE_TUTOR:
            items.append(Item(price_ref(price), max(0, seats - price.included_quantity)))
        elif price.component == PlanPrice.Component.BRANCH:
            items.append(Item(price_ref(price), max(0, branches - price.included_quantity)))
        else:
            items.append(Item(price_ref(price), 1))
    return items


# --- subscription state -------------------------------------------------------------------------


def current() -> Subscription | None:
    return Subscription.objects.select_related("plan", "pending_plan").first()


def _require() -> Subscription:
    subscription = current()
    if subscription is None:
        raise NotFound(_("This organisation has no subscription."))
    return subscription


def _locked() -> Subscription:
    subscription = (
        Subscription.objects.select_for_update(of=("self",))
        .select_related("plan", "pending_plan")
        .first()
    )
    if subscription is None:
        raise NotFound(_("This organisation has no subscription."))
    return subscription


def _organisation() -> Organisation:
    return Organisation.objects.get(pk=require_organisation_id())


def _event_base(subscription: Subscription) -> dict[str, Any]:
    return {
        "subject_id": subscription.pk,
        "plan": subscription.plan.key,
        "status": subscription.status,
    }


def _changed(subscription: Subscription, change: str, invoice_id: str = "") -> None:
    entitlements.invalidate(subscription.organisation_id)
    publish(
        events.SubscriptionChanged(
            **_event_base(subscription), change=change, invoice_id=invoice_id
        )
    )


def _sync_org(subscription: Subscription, reason: str = "") -> None:
    """Bring the organisation's status in line with the subscription."""
    from tutortrack.tenancy import lifecycle

    org = _organisation()
    if org.is_closed:
        return
    status = subscription.status
    if status in (Subscription.Status.SUSPENDED, Subscription.Status.CANCELLED):
        if not org.is_suspended:
            lifecycle.suspend_organisation(org, reason=reason or status)
        return
    target = {
        Subscription.Status.TRIALING: Organisation.Status.TRIAL,
        Subscription.Status.ACTIVE: Organisation.Status.ACTIVE,
        Subscription.Status.PAST_DUE: Organisation.Status.PAST_DUE,
    }[Subscription.Status(status)]
    if org.is_suspended:
        lifecycle.reactivate_organisation(
            org, status=target if target != Organisation.Status.PAST_DUE else "active"
        )
        org.refresh_from_db()
    if org.status != target:
        lifecycle.set_billing_status(org, target)


def notify_owners(kind: str, title: str, body: str, *, key: str) -> None:
    """In-app and email notice to everyone holding ``subscription.view``."""
    from tutortrack.comms import services as comms

    comms.notify("subscription_notice", (title, body, PLAN_PAGE), key=f"{kind}:{key}")


@transaction.atomic
def start_trial(organisation: Organisation) -> Subscription:
    """Every new organisation starts a trial with the trial plan's features (FR-04-3); the
    plan it will move to is picked from the business type and can be changed any time."""
    with tenant_context(organisation):
        existing = current()
        if existing is not None:
            return existing
        plan = get_plan(DEFAULT_PLAN_FOR.get(organisation.business_type, "agency"))
        started = now()
        subscription = Subscription.objects.create(
            plan=plan,
            currency=currency_for(organisation),
            status=Subscription.Status.TRIALING,
            trial_started_at=started,
            trial_ends_at=started + timedelta(days=int(settings.SUBSCRIPTIONS["TRIAL_DAYS"])),
        )
        audit.record_create(subscription)
        _sync_org(subscription)
        entitlements.invalidate(organisation.pk)
        from . import credits

        credits.reset_allowances(ref="trial")
        publish(
            events.SubscriptionStarted(
                **_event_base(subscription),
                trial_ends_at=subscription.trial_ends_at.isoformat()
                if subscription.trial_ends_at
                else None,
            )
        )
    return subscription


@transaction.atomic
def extend_trial(days: int, *, reason: str = "") -> Subscription:
    """Platform admin gives a trial more time (signals the trial workflow)."""
    if not 1 <= days <= 90:
        raise BusinessRuleViolation(_("Extend by 1 to 90 days."))
    subscription = _locked()
    if subscription.status not in (Subscription.Status.TRIALING, Subscription.Status.SUSPENDED):
        raise BusinessRuleViolation(_("Only trials can be extended."))
    with audit.track(subscription, action="extend_trial"):
        base = max(subscription.trial_ends_at or now(), now())
        subscription.trial_ends_at = base + timedelta(days=days)
        restart = subscription.status == Subscription.Status.SUSPENDED
        subscription.status = Subscription.Status.TRIALING
        subscription.save(update_fields=["trial_ends_at", "status", "updated_at"])
    _sync_org(subscription)
    _changed(subscription, "trial_extended")
    from tutortrack.core.workflows import start

    from .processes import TrialInput, TrialLifecycleWorkflow, trial_workflow_id

    if restart:  # the lifecycle already ended with a lock: run it again for the new end
        ends = subscription.trial_ends_at
        start(
            TrialLifecycleWorkflow,
            TrialInput(
                organisation_id=str(subscription.organisation_id),
                trial_ends_at=ends.isoformat(),
                welcome=False,
            ),
            id=f"{trial_workflow_id(subscription.organisation_id)}:{ends:%Y%m%d%H%M}",
            subject=("subscription", str(subscription.pk)),
        )
    else:
        signal_trial("extended", days)
    return subscription


def trial_notice(stage: str) -> bool:
    """One trial email (FR-04-3). False when the trial is over or already converted."""
    subscription = current()
    if subscription is None or subscription.status != Subscription.Status.TRIALING:
        return False
    if stage in ("reminder", "last_chance") and subscription.stripe_subscription_id:
        return False  # they've chosen a plan and added a card
    texts = {
        "welcome": (
            _("Welcome to TutorTrack"),
            _("Your free trial includes every Agency feature. Choose a plan whenever you're "
              "ready from Billing & plan."),
        ),
        "checklist": (
            _("Getting the most from your trial"),
            _("Add your tutors and students, schedule your first lessons and send your first "
              "invoice. Help is a click away in the app."),
        ),
        "reminder": (
            _("Your trial ends in 7 days"),
            _("Choose a plan and add a payment method to keep everything running."),
        ),
        "last_chance": (
            _("Your trial ends in 2 days"),
            _("Add a payment method now so your account doesn't become read-only."),
        ),
    }  # fmt: skip
    title, body = texts[stage]
    ends = subscription.trial_ends_at
    with transaction.atomic():
        if stage == "reminder":
            publish(
                events.SubscriptionTrialEnding(
                    **_event_base(subscription),
                    trial_ends_at=subscription.trial_ends_at.isoformat()
                    if subscription.trial_ends_at
                    else "",
                )
            )
        notify_owners("trial", title, body, key=f"{stage}:{ends:%Y%m%d}" if ends else stage)
    return True


@transaction.atomic
def end_trial(at: datetime | None = None) -> str:
    """Trial over: carry on with the chosen plan if there's a payment method, otherwise
    lock the account read-only until they subscribe (FR-04-3). ``at``: the workflow's
    clock."""
    subscription = _locked()
    if subscription.status != Subscription.Status.TRIALING:
        return str(subscription.status)
    if subscription.trial_ends_at and subscription.trial_ends_at > (at or now()) + timedelta(
        minutes=5
    ):
        return f"extended:{subscription.trial_ends_at.isoformat()}"
    if subscription.stripe_subscription_id and not subscription.cancel_at_period_end:
        with audit.track(subscription, action="trial_converted"):
            subscription.status = Subscription.Status.ACTIVE
            subscription.save(update_fields=["status", "updated_at"])
        _sync_org(subscription)
        _start_paid_period(subscription.stripe_subscription_id)
        _changed(subscription, "activated")
        return "active"
    with audit.track(subscription, action="trial_expired"):
        subscription.status = Subscription.Status.SUSPENDED
        subscription.save(update_fields=["status", "updated_at"])
    reason = _("Trial ended. Choose a plan to carry on.")
    _sync_org(subscription, reason)
    entitlements.invalidate(subscription.organisation_id)
    publish(events.SubscriptionSuspended(**_event_base(subscription), reason="trial_expired"))
    notify_owners(
        "trial", _("Your trial has ended"),
        _("Your account is read-only for now. Choose a plan to pick up where you left off: "
          "nothing has been deleted."),
        key="expired",
    )  # fmt: skip
    return "locked"


# --- Stripe customer and checkout (FR-04-4) -----------------------------------------------------


def _start_paid_period(ref: str) -> None:
    """The trial's allowance gives way to the paid plan's."""
    from . import credits

    credits.reset_allowances(ref=f"start:{ref}")


def _ensure_customer(subscription: Subscription) -> str:
    if subscription.stripe_customer_id:
        return subscription.stripe_customer_id
    org = _organisation()
    from tutortrack.identity.models import Membership

    owner = Membership.objects.filter(role=Membership.Role.OWNER).select_related("user").first()
    email = org.contact_email or (owner.user.email if owner else "")
    ref = get_gateway().create_customer(
        name=org.legal_name or org.name, email=email, organisation_id=str(org.pk),
        country=org.country, vat_number=org.vat_number,
    )  # fmt: skip
    CustomerRoute.objects.update_or_create(organisation_id=org.pk, defaults={"customer_ref": ref})
    Subscription.objects.filter(pk=subscription.pk).update(stripe_customer_id=ref)
    subscription.stripe_customer_id = ref
    return ref


def _urls() -> tuple[str, str]:
    base = _organisation().base_url
    return f"{base}{PLAN_PAGE}?checkout={{CHECKOUT_SESSION_ID}}", f"{base}{PLAN_PAGE}"


def _plan_and_interval(plan_key: str, interval: str) -> Plan:
    if interval not in Interval.values:
        raise BusinessRuleViolation(_("Choose monthly or annual billing."))
    plan = get_plan(plan_key)
    if plan.visibility != Plan.Visibility.PUBLIC:
        raise BusinessRuleViolation(
            _("This plan isn't available to choose. Contact us to set it up."),
            extra={"code": "contact_sales"},
        )
    return plan


def checkout(plan_key: str, interval: str) -> str:
    """A Stripe Checkout URL to start paying for ``plan`` (from a trial, or to resubscribe
    after the account became read-only)."""
    subscription = _require()
    plan = _plan_and_interval(plan_key, interval)
    if subscription.stripe_subscription_id and subscription.status not in (
        Subscription.Status.CANCELLED,
    ):
        raise Conflict(_("You already have a subscription: change plan instead."))
    blockers = downgrade_blockers(plan)
    if blockers:
        raise BusinessRuleViolation(
            _("Some things need to change before you can move to this plan."),
            extra={"blockers": blockers},
        )
    items = items_for(subscription, plan, interval)
    customer = _ensure_customer(subscription)
    trial_end = None
    if (
        subscription.status == Subscription.Status.TRIALING
        and subscription.trial_ends_at
        and subscription.trial_ends_at > now() + timedelta(hours=49)
    ):
        trial_end = subscription.trial_ends_at  # keep the rest of the free trial
    success, cancel = _urls()
    try:
        session = get_gateway().checkout_subscription(
            customer=customer, items=items, success_url=success, cancel_url=cancel,
            trial_end=trial_end,
            metadata={"organisation_id": str(subscription.organisation_id), "plan": plan.key,
                      "interval": interval},
        )  # fmt: skip
    except GatewayError as exc:
        raise BusinessRuleViolation(str(exc)) from exc
    return session.url


@transaction.atomic
def complete_checkout(session_id: str) -> Subscription:
    """Called on return from Checkout (and by the ``checkout.session.completed`` webhook)."""
    try:
        result = get_gateway().retrieve_checkout(session_id)
    except GatewayError as exc:
        raise BusinessRuleViolation(str(exc)) from exc
    subscription = _locked()
    if result.metadata.get("organisation_id") != str(subscription.organisation_id):
        raise NotFound(_("Unknown checkout session."))
    if result.mode == "payment":
        from . import credits

        credits.complete_checkout(result)
        return subscription
    if not result.complete or not result.subscription:
        return subscription
    if subscription.stripe_subscription_id == result.subscription:
        return subscription
    remote = get_gateway().retrieve_subscription(result.subscription)
    with audit.track(subscription, action="subscribe"):
        subscription.stripe_subscription_id = remote.id
        subscription.stripe_customer_id = remote.customer
        subscription.cancel_at_period_end = False
        subscription.cancelled_at = None
        subscription.save()
    _apply_remote(subscription, remote)
    if subscription.status == Subscription.Status.ACTIVE:
        _start_paid_period(remote.id)
    _changed(subscription, "converted")
    if subscription.status == Subscription.Status.TRIALING:
        signal_trial("converted")
    return subscription


def signal_trial(name: str, arg: Any = None) -> None:
    """Signal the organisation's running trial workflow after commit (if there is one)."""
    from tutortrack.core.models import WorkflowLink
    from tutortrack.core.workflows import signal_now

    from .processes import TRIAL_PROCESS

    def send() -> None:
        link = WorkflowLink.objects.filter(process=TRIAL_PROCESS, status="running").first()
        if link is not None:
            signal_now(link.workflow_id, name, arg)

    transaction.on_commit(send)


def portal_url() -> str:
    subscription = _require()
    if not subscription.stripe_customer_id:
        raise BusinessRuleViolation(_("Choose a plan first."))
    try:
        return get_gateway().portal_url(
            customer=subscription.stripe_customer_id, return_url=_urls()[1]
        )
    except GatewayError as exc:
        raise BusinessRuleViolation(str(exc)) from exc


REMOTE_STATUS = {
    "trialing": Subscription.Status.TRIALING,
    "active": Subscription.Status.ACTIVE,
    "past_due": Subscription.Status.PAST_DUE,
    "unpaid": Subscription.Status.PAST_DUE,
    "canceled": Subscription.Status.CANCELLED,
}


def _apply_remote(subscription: Subscription, remote: RemoteSubscription) -> None:
    """Mirror Stripe's view: plan and interval (from the base price), period and status.
    Our own suspension for non-payment sticks until a payment succeeds."""
    fields = ["current_period_start", "current_period_end", "cancel_at_period_end"]
    subscription.current_period_start = remote.current_period_start
    subscription.current_period_end = remote.current_period_end
    subscription.cancel_at_period_end = remote.cancel_at_period_end
    prices = [p for p in (price_for_ref(ref) for ref in remote.price_ids) if p is not None]
    if prices:
        plan_changed = prices[0].plan_id != subscription.plan_id
        subscription.plan = prices[0].plan
        subscription.interval = prices[0].interval
        fields += ["plan", "interval"]
        if plan_changed and subscription.pending_plan_id == prices[0].plan_id:
            subscription.pending_plan = None
            subscription.pending_interval = ""
            fields += ["pending_plan", "pending_interval"]
    status = REMOTE_STATUS.get(remote.status)
    keep_suspended = subscription.status == Subscription.Status.SUSPENDED and status in (
        Subscription.Status.PAST_DUE,
    )
    trial_running = bool(subscription.trial_ends_at and subscription.trial_ends_at > now())
    if status == Subscription.Status.TRIALING and not trial_running:
        status = Subscription.Status.ACTIVE
    if status is not None and not keep_suspended and status != subscription.status:
        subscription.status = status
        if status == Subscription.Status.ACTIVE:
            subscription.past_due_since = None
            fields.append("past_due_since")
        fields.append("status")
    subscription.save(update_fields=[*fields, "updated_at"])
    _sync_org(subscription)
    entitlements.invalidate(subscription.organisation_id)


# --- plan changes (FR-04-5) ---------------------------------------------------------------------


@dataclass
class ChangePreview:
    plan: str
    interval: str
    direction: str  # upgrade | downgrade | same
    effective: str  # now | period_end | checkout
    blockers: list[str] = field(default_factory=list)
    amount_due_now: Money | None = None
    next_period_total: Money | None = None


def downgrade_blockers(plan: Plan) -> list[str]:
    """What must change before moving to ``plan`` (e.g. too many tutors for Solo)."""
    limits = {e.key: e.int_value for e in plan.entitlements.filter(key__in=LIMITS)}
    usage = selectors.usage_counts()
    messages = {
        "max_tutors": _("You have %(used)s tutors; %(plan)s allows %(allowed)s. Deactivate or "
                        "archive %(over)s first."),
        "max_branches": _("You have %(used)s branches; %(plan)s allows %(allowed)s. Archive "
                          "%(over)s first."),
        "max_active_students": _("You have %(used)s active students; %(plan)s allows "
                                 "%(allowed)s. Change %(over)s to another status first."),
    }  # fmt: skip
    out = []
    for key, template in messages.items():
        allowed = limits.get(key)
        used = usage[key]
        if allowed is not None and used > allowed:
            out.append(template % {"used": used, "plan": plan.name, "allowed": allowed,
                                   "over": used - allowed})  # fmt: skip
    storage_limit = limits.get("storage_gb")
    if storage_limit is not None and usage["storage_gb"] > storage_limit * selectors.BYTES_PER_GB:
        out.append(
            _("Your files use more than the %(allowed)s GB %(plan)s includes.")
            % {"allowed": storage_limit, "plan": plan.name}
        )
    return out


def _direction(subscription: Subscription, plan: Plan, interval: str) -> str:
    if plan.rank > subscription.plan.rank:
        return "upgrade"
    if plan.rank < subscription.plan.rank:
        return "downgrade"
    if plan.pk != subscription.plan_id:
        return "downgrade"  # a sideways move (e.g. per-tutor ↔ revenue share) waits
    if interval == subscription.interval:
        return "same"
    return "upgrade" if interval == Interval.YEAR else "downgrade"


def preview_change(plan_key: str, interval: str) -> ChangePreview:
    subscription = _require()
    plan = _plan_and_interval(plan_key, interval)
    direction = _direction(subscription, plan, interval)
    preview = ChangePreview(plan.key, interval, direction, "now")
    preview.blockers = downgrade_blockers(plan) if direction != "upgrade" else []
    if not subscription.stripe_subscription_id or subscription.status == "cancelled":
        preview.effective = "checkout" if subscription.status != "trialing" else "now"
        return preview
    items = items_for(subscription, plan, interval)
    try:
        if direction == "upgrade":
            preview.amount_due_now = get_gateway().preview_change(
                subscription.stripe_subscription_id, items
            )
        else:
            preview.effective = "period_end"
    except GatewayError as exc:
        logger.warning("subscriptions.preview_failed", error=str(exc))
    return preview


@transaction.atomic
def change_plan(plan_key: str, interval: str) -> Subscription:
    """Upgrade now with proration; downgrade (or annual → monthly) at the period end,
    after checking nothing exceeds the smaller plan. During a trial without a card this
    just records the plan the trial will move to."""
    subscription = _locked()
    plan = _plan_and_interval(plan_key, interval)
    direction = _direction(subscription, plan, interval)
    if direction != "upgrade":
        blockers = downgrade_blockers(plan)
        if blockers:
            raise BusinessRuleViolation(
                _("Some things need to change before you can move to this plan."),
                extra={"blockers": blockers},
            )
    if direction == "same" and not subscription.pending_plan_id:
        return subscription
    if not subscription.stripe_subscription_id:
        if subscription.status != Subscription.Status.TRIALING:
            raise BusinessRuleViolation(
                _("Add a payment method to choose a plan."), extra={"code": "checkout_required"}
            )
        with audit.track(subscription, action="choose_plan"):
            subscription.plan = plan
            subscription.interval = interval
            subscription.save(update_fields=["plan", "interval", "updated_at"])
        _changed(subscription, "plan")
        return subscription
    items = items_for(subscription, plan, interval)
    gateway = get_gateway()
    try:
        if direction == "upgrade" or (direction == "same" and subscription.pending_plan_id):
            remote = gateway.update_items(subscription.stripe_subscription_id, items, prorate=True)
            with audit.track(subscription, action="change_plan"):
                subscription.pending_plan = None
                subscription.pending_interval = ""
                _apply_remote(subscription, remote)
                subscription.plan = plan
                subscription.interval = interval
                subscription.save()
            _changed(subscription, "plan")
        else:
            gateway.schedule_items(subscription.stripe_subscription_id, items)
            with audit.track(subscription, action="schedule_plan"):
                subscription.pending_plan = plan
                subscription.pending_interval = interval
                subscription.save(update_fields=["pending_plan", "pending_interval", "updated_at"])
            _changed(subscription, "scheduled")
    except GatewayError as exc:
        raise BusinessRuleViolation(str(exc)) from exc
    return subscription


CANCEL_REASONS = ("too_expensive", "missing_features", "switching", "closing", "other")


@transaction.atomic
def cancel(reason: str, feedback: str = "") -> Subscription:
    """Cancel at the period end (or trial end), with an exit survey."""
    if reason not in CANCEL_REASONS:
        raise BusinessRuleViolation(_("Tell us why you're leaving."))
    subscription = _locked()
    if subscription.status in (Subscription.Status.CANCELLED, Subscription.Status.SUSPENDED):
        raise BusinessRuleViolation(_("The subscription has already ended."))
    if subscription.stripe_subscription_id:
        try:
            get_gateway().set_cancel_at_period_end(subscription.stripe_subscription_id, True)
        except GatewayError as exc:
            raise BusinessRuleViolation(str(exc)) from exc
    with audit.track(subscription, action="cancel"):
        subscription.cancel_at_period_end = True
        subscription.cancellation_reason = reason
        subscription.cancellation_feedback = feedback[:2000]
        subscription.save()
    _changed(subscription, "cancel_scheduled")
    return subscription


@transaction.atomic
def reactivate() -> tuple[Subscription, str]:
    """Undo a scheduled cancellation, or after it ended (within the retention period)
    return a Checkout URL to subscribe again."""
    subscription = _locked()
    if subscription.cancel_at_period_end and subscription.status not in (
        Subscription.Status.CANCELLED, Subscription.Status.SUSPENDED,
    ):  # fmt: skip
        if subscription.stripe_subscription_id:
            try:
                get_gateway().set_cancel_at_period_end(subscription.stripe_subscription_id, False)
            except GatewayError as exc:
                raise BusinessRuleViolation(str(exc)) from exc
        with audit.track(subscription, action="reactivate"):
            subscription.cancel_at_period_end = False
            subscription.cancellation_reason = ""
            subscription.save()
        _changed(subscription, "cancel_undone")
        return subscription, ""
    if subscription.status in (Subscription.Status.CANCELLED, Subscription.Status.SUSPENDED):
        if subscription.status == Subscription.Status.SUSPENDED and (
            subscription.stripe_subscription_id
        ):
            return subscription, portal_url()  # unpaid: update the card, Stripe retries
        return subscription, checkout(subscription.plan.key, subscription.interval)
    raise BusinessRuleViolation(_("The subscription is active."))


# --- dunning (FR-04-6) --------------------------------------------------------------------------


@transaction.atomic
def mark_past_due(invoice_id: str) -> Subscription:
    subscription = _locked()
    if subscription.status in (Subscription.Status.PAST_DUE, Subscription.Status.SUSPENDED):
        return subscription
    with audit.track(subscription, action="past_due"):
        subscription.status = Subscription.Status.PAST_DUE
        subscription.past_due_since = now()
        subscription.save(update_fields=["status", "past_due_since", "updated_at"])
    _sync_org(subscription)
    entitlements.invalidate(subscription.organisation_id)
    publish(events.SubscriptionPastDue(**_event_base(subscription), invoice_id=invoice_id))
    return subscription


def still_past_due() -> bool:
    subscription = current()
    return bool(subscription and subscription.status == Subscription.Status.PAST_DUE)


def dunning_notice(day: int, suspend_after: int) -> bool:
    subscription = current()
    if subscription is None or subscription.status != Subscription.Status.PAST_DUE:
        return False
    if day == 0:
        title = _("We couldn't take your TutorTrack payment")
        body = _("Please update your payment details to avoid any interruption.")
    else:
        title = _("Reminder: your TutorTrack payment is overdue")
        body = _("Your account becomes read-only in %(days)s days unless the payment goes "
                 "through. Update your payment details to fix it.") % {
            "days": max(suspend_after - day, 1)
        }  # fmt: skip
    since = subscription.past_due_since or now()
    with transaction.atomic():
        notify_owners("dunning", title, body, key=f"{since:%Y%m%d%H%M}:{day}")
    return True


@transaction.atomic
def suspend_for_non_payment() -> bool:
    subscription = _locked()
    if subscription.status != Subscription.Status.PAST_DUE:
        return False
    with audit.track(subscription, action="suspend"):
        subscription.status = Subscription.Status.SUSPENDED
        subscription.save(update_fields=["status", "updated_at"])
    _sync_org(subscription, _("Subscription payment overdue."))
    entitlements.invalidate(subscription.organisation_id)
    publish(events.SubscriptionSuspended(**_event_base(subscription), reason="non_payment"))
    notify_owners(
        "dunning", _("Your account is read-only"),
        _("We still couldn't collect your TutorTrack payment, so the account is read-only and "
          "portals and automations are paused. Paying restores everything straight away."),
        key="suspended",
    )  # fmt: skip
    return True


@transaction.atomic
def payment_recovered(invoice_id: str) -> Subscription:
    """A payment succeeded: restore immediately (FR-04-6)."""
    subscription = _locked()
    if subscription.status not in (Subscription.Status.PAST_DUE, Subscription.Status.SUSPENDED):
        return subscription
    if subscription.status == Subscription.Status.SUSPENDED and not (
        subscription.stripe_subscription_id
    ):
        return subscription  # a trial lock: only subscribing lifts it
    with audit.track(subscription, action="payment_recovered"):
        subscription.status = Subscription.Status.ACTIVE
        subscription.past_due_since = None
        subscription.save(update_fields=["status", "past_due_since", "updated_at"])
    _sync_org(subscription)
    _changed(subscription, "payment_recovered", invoice_id)
    return subscription


@transaction.atomic
def mark_cancelled() -> Subscription:
    """Stripe ended the subscription (cancelled at period end, or unpaid for good)."""
    subscription = _locked()
    if subscription.status == Subscription.Status.CANCELLED:
        return subscription
    with audit.track(subscription, action="ended"):
        subscription.status = Subscription.Status.CANCELLED
        subscription.cancelled_at = now()
        subscription.cancel_at_period_end = False
        subscription.save()
    _sync_org(subscription, _("Subscription cancelled. Subscribe again to carry on."))
    entitlements.invalidate(subscription.organisation_id)
    publish(events.SubscriptionCancelled(**_event_base(subscription)))
    return subscription


# --- seats and usage (FR-04-4, T05) -------------------------------------------------------------


def sync_seats() -> int | None:
    """Push the billable tutor and branch counts to Stripe when they changed."""
    subscription = current()
    if subscription is None or not subscription.stripe_subscription_id:
        return None
    if subscription.status in (Subscription.Status.CANCELLED,):
        return None
    seats = selectors.billable_tutors(subscription)
    branches = selectors.branch_count()
    gateway = get_gateway()
    for price in plan_prices(subscription.plan, subscription.currency, subscription.interval):
        if price.component == PlanPrice.Component.ACTIVE_TUTOR:
            quantity = max(0, seats - price.included_quantity)
        elif price.component == PlanPrice.Component.BRANCH:
            quantity = max(0, branches - price.included_quantity)
        else:
            continue
        gateway.set_quantity(subscription.stripe_subscription_id, price_ref(price), quantity)
    Subscription.objects.filter(pk=subscription.pk).update(seats=seats, seats_synced_at=now())
    return seats


def report_revenue(day: Any) -> MeterReport | None:
    """Report one day's processed payments to the revenue-share meter (idempotent)."""
    from datetime import UTC, datetime, time

    from tutortrack.payments.selectors import processed_totals

    subscription = current()
    if subscription is None or not subscription.stripe_customer_id:
        return None
    has_share = PlanPrice.objects.filter(
        plan=subscription.plan, currency=subscription.currency,
        component=PlanPrice.Component.REVENUE_SHARE,
    ).exists()  # fmt: skip
    if not has_share:
        return None
    start = datetime.combine(day, time(0), tzinfo=UTC)
    totals = processed_totals(start, start + timedelta(days=1))
    amount = totals.get(subscription.currency)
    minor = Money(amount, subscription.currency).to_minor() if amount else 0
    identifier = f"rev:{subscription.organisation_id}:{day.isoformat()}"
    report, _created = MeterReport.objects.get_or_create(
        identifier=identifier,
        defaults={"meter": REVENUE_METER, "period_date": day, "quantity": minor},
    )
    if report.reported_at is None:
        get_gateway().report_usage(
            event_name=REVENUE_METER, customer=subscription.stripe_customer_id,
            value=report.quantity, identifier=identifier, timestamp=start + timedelta(hours=12),
        )  # fmt: skip
        MeterReport.objects.filter(pk=report.pk).update(reported_at=now())
    return report


# --- entitlement overrides (platform admin) -----------------------------------------------------


@transaction.atomic
def set_override(
    key: str, *, enabled: bool | None = None, limit: int | None = None, unlimited: bool = False,
    expires_at: datetime | None = None, reason: str = "", user: Any = None,
) -> EntitlementOverride:  # fmt: skip
    from .catalogue import FEATURES

    if key not in FEATURES and key not in LIMITS:
        raise BusinessRuleViolation(_("Unknown entitlement."))
    if key in FEATURES and enabled is None:
        raise BusinessRuleViolation(_("Say whether the feature is on or off."))
    if key in LIMITS and limit is None and not unlimited:
        raise BusinessRuleViolation(_("Give a limit, or make it unlimited."))
    override, _created = EntitlementOverride.objects.update_or_create(
        key=key,
        defaults={
            "bool_value": enabled if key in FEATURES else None,
            "int_value": limit if key in LIMITS else None,
            "unlimited": unlimited,
            "expires_at": expires_at,
            "reason": reason[:255],
            "granted_by": user,
        },
    )
    audit.record(override, "set", {"key": [None, key], "reason": [None, reason[:255]]})
    entitlements.invalidate(require_organisation_id())
    return override


@transaction.atomic
def remove_override(key: str) -> None:
    EntitlementOverride.objects.filter(key=key).delete()
    entitlements.invalidate(require_organisation_id())


# --- webhooks -----------------------------------------------------------------------------------


def ingest_webhook(payload: bytes, signature: str) -> BillingEvent | None:
    """Verify, route by customer and store; processing happens in a task."""
    event = get_gateway().parse_webhook(payload, signature)
    data = event.data
    customer = data.get("customer") if isinstance(data.get("customer"), str) else ""
    if data.get("object") == "customer":
        customer = data.get("id", "")
    route = CustomerRoute.objects.filter(customer_ref=customer).first() if customer else None
    if route is None:
        return None
    with tenant_context(route.organisation_id), transaction.atomic():
        row, created = BillingEvent.objects.get_or_create(
            event_id=event.id, defaults={"type": event.type, "payload": event.payload}
        )
        if created:
            org_id, row_id = route.organisation_id, row.pk
            transaction.on_commit(lambda: _process_later(org_id, row_id))
    return row


def _process_later(organisation_id: Any, event_id: Any) -> None:
    from .tasks import process_billing_event

    process_billing_event.delay(organisation_id=str(organisation_id), event_id=str(event_id))


def process_event(row: BillingEvent) -> None:
    """Apply one stored Stripe Billing event (idempotent)."""
    if row.processed_at:
        return
    data = row.payload["data"]["object"]
    kind = row.type
    subscription = current()
    if subscription is not None:
        _apply_event(subscription, kind, data)
    BillingEvent.objects.filter(pk=row.pk).update(processed_at=now(), error="")


def _apply_event(subscription: Subscription, kind: str, data: dict[str, Any]) -> None:
    from . import credits

    sub_ref = data.get("subscription") or data.get("parent", {}).get(
        "subscription_details", {}
    ).get("subscription")
    if kind == "checkout.session.completed":
        if data.get("mode") == "payment":
            credits.complete_purchase_ref(data.get("metadata", {}).get("credit_purchase", ""),
                                          data.get("payment_intent") or "")  # fmt: skip
        elif data.get("subscription"):
            with transaction.atomic():
                if subscription.stripe_subscription_id != data["subscription"]:
                    complete_checkout(data["id"])
    elif kind in ("customer.subscription.created", "customer.subscription.updated"):
        if data["id"] == subscription.stripe_subscription_id or not (
            subscription.stripe_subscription_id
        ):
            remote = get_gateway().retrieve_subscription(data["id"])
            with transaction.atomic():
                locked = _locked()
                if not locked.stripe_subscription_id:
                    locked.stripe_subscription_id = remote.id
                    locked.save(update_fields=["stripe_subscription_id", "updated_at"])
                _apply_remote(locked, remote)
    elif kind == "customer.subscription.deleted":
        if data["id"] == subscription.stripe_subscription_id:
            mark_cancelled()
    elif kind == "customer.subscription.trial_will_end":
        pass  # the trial workflow already sends the reminders
    elif not sub_ref or sub_ref != subscription.stripe_subscription_id:
        return  # an invoice for something else (e.g. a credit top-up)
    elif kind == "invoice.payment_failed":
        mark_past_due(data["id"])
    elif kind == "invoice.paid":
        payment_recovered(data["id"])
        if data.get("billing_reason") in ("subscription_cycle", "subscription_create"):
            with transaction.atomic():
                credits.reset_allowances(ref=data["id"])

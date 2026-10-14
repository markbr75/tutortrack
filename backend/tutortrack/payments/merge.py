"""Payments follow a merged client (FR-05-13): payments (amounts untouched), saved payment
methods, provider customers, setup links, auto-pay consents, reconciliation matches and
provider migrations.

A saved method lives under the provider's customer record. When both clients are
customers of the same provider account, only the survivor's customer is kept, so the
merged client's saved methods there are retired (they can't be charged under another
customer) and the family is asked to add them again."""

from __future__ import annotations

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l

from tutortrack.people.merging import (
    MergeContext,
    MergeProvider,
    Move,
    count,
    moves,
    register,
    repoint,
)

from .models import (
    AutoPayConsent,
    Payment,
    PaymentMethod,
    ProviderCustomer,
    ProviderMigration,
    ReconciliationMatch,
    SetupLink,
)

RECORDS = (
    ("payments.payments", _l("Payments"), Payment),
    ("payments.methods", _l("Saved payment methods"), PaymentMethod),
    ("payments.setup_links", _l("Payment setup links"), SetupLink),
    ("payments.autopay_consents", _l("Auto-pay consents"), AutoPayConsent),
    ("payments.reconciliation", _l("Bank reconciliation matches"), ReconciliationMatch),
    ("payments.migrations", _l("Provider migrations"), ProviderMigration),
)


def _shared_accounts(ctx: MergeContext) -> set[object]:
    ours = set(
        ProviderCustomer.objects.filter(client=ctx.target).values_list("account_id", flat=True)
    )
    theirs = set(
        ProviderCustomer.objects.filter(client=ctx.source).values_list("account_id", flat=True)
    )
    return ours & theirs


def _check(ctx: MergeContext) -> list[str]:
    waiting = ProviderMigration.objects.filter(status__in=["waiting", "switched"])
    if waiting.filter(client=ctx.source).exists() and waiting.filter(client=ctx.target).exists():
        return [_("Both clients are moving payment provider. Finish one move first.")]
    return []


def _notes(ctx: MergeContext) -> list[str]:
    shared = _shared_accounts(ctx)
    if (
        shared
        and PaymentMethod.objects.filter(
            client=ctx.source, account_id__in=shared, status=PaymentMethod.Status.ACTIVE
        ).exists()
    ):
        return [
            _(
                "Saved payment methods of the merged client at the same payment provider "
                "can't be moved. The family will need to add them again."
            )
        ]
    return []


def _count(ctx: MergeContext) -> list[Move]:
    return moves(
        *[(key, label, count(model, "client", ctx)) for key, label, model in RECORDS],
        (
            "payments.customers",
            _l("Payment provider customers"),
            count(ProviderCustomer, "client", ctx),
        ),
    )


def _merge(ctx: MergeContext) -> list[Move]:
    shared = _shared_accounts(ctx)
    retired = 0
    if shared:
        retired = PaymentMethod.objects.filter(
            client=ctx.source, account_id__in=shared, status=PaymentMethod.Status.ACTIVE
        ).update(status=PaymentMethod.Status.REMOVED, is_default=False)
        ProviderCustomer.objects.filter(client=ctx.source, account_id__in=shared).delete()
        if retired:
            ctx.note(
                _("%(n)s saved payment method(s) of the merged client were retired.")
                % {"n": retired}
            )
    if PaymentMethod.objects.filter(
        client=ctx.target, is_default=True, status=PaymentMethod.Status.ACTIVE
    ).exists():
        PaymentMethod.objects.filter(client=ctx.source, is_default=True).update(is_default=False)
    customers = repoint(ProviderCustomer, "client", ctx)
    return moves(
        *[(key, label, repoint(model, "client", ctx)) for key, label, model in RECORDS],
        ("payments.customers", _l("Payment provider customers"), customers),
        ("payments.retired_methods", _l("Saved payment methods retired"), retired),
    )


register(
    MergeProvider(
        key="payments",
        label="Payments",
        subject_types=frozenset({"people.client"}),
        count=_count,
        merge=_merge,
        check=_check,
        notes=_notes,
        order=55,
    )
)

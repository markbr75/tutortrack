"""Pricing follows a merged client or student (FR-05-13): client and student discounts,
promo code redemptions and contract price lists (a list both are on is kept once)."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _l

from tutortrack.people.merging import (
    MergeContext,
    MergeProvider,
    Move,
    count,
    moves,
    register,
    repoint,
    repoint_unique,
)

from .models import DiscountRule, PriceListClient, PromoRedemption


def _count(ctx: MergeContext) -> list[Move]:
    if ctx.subject_type == "people.student":
        return moves(("catalogue.discounts", _l("Discounts"), count(DiscountRule, "student", ctx)))
    return moves(
        ("catalogue.discounts", _l("Discounts"), count(DiscountRule, "client", ctx)),
        ("catalogue.promos", _l("Promo code uses"), count(PromoRedemption, "client", ctx)),
        ("catalogue.price_lists", _l("Price lists"), count(PriceListClient, "client", ctx)),
    )


def _merge(ctx: MergeContext) -> list[Move]:
    if ctx.subject_type == "people.student":
        return moves(
            ("catalogue.discounts", _l("Discounts"), repoint(DiscountRule, "student", ctx))
        )
    lists, _dropped = repoint_unique(PriceListClient, "client", ctx, ["price_list_id"])
    return moves(
        ("catalogue.discounts", _l("Discounts"), repoint(DiscountRule, "client", ctx)),
        ("catalogue.promos", _l("Promo code uses"), repoint(PromoRedemption, "client", ctx)),
        ("catalogue.price_lists", _l("Price lists"), lists),
    )


register(
    MergeProvider(
        key="catalogue",
        label="Pricing",
        subject_types=frozenset({"people.client", "people.student"}),
        count=_count,
        merge=_merge,
        order=60,
    )
)

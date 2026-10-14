"""Portal pages for E25: the client's referral page (FR-25-2), the tutor's referral page
(FR-25-4) and the affiliate portal (FR-25-3). Every view starts from the signed-in
person's own record, so other families' or affiliates' data are never found."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.exceptions import FeatureDisabled, PermissionDenied
from tutortrack.core.permissions import HasOrganisation, has_perm
from tutortrack.portal.api.views import PortalView

from .. import selectors, services
from ..models import Affiliate, AffiliateStatement, TutorReferral
from . import serializers as s


def _link(path: str) -> str:
    from tutortrack.comms.catalogue import tenant_link

    return tenant_link(path)


def _program(program: Any) -> dict[str, Any] | None:
    if program is None:
        return None
    return {
        "name": program.name,
        "referrer_reward": program.referrer_reward.to_dict(),
        "referrer_reward_kind": program.referrer_reward_kind,
        "milestone": program.milestone,
        "milestone_lessons": program.milestone_lessons,
        "referee_discount_percent": program.referee_discount_percent,
        "terms": program.terms,
    }


class PortalReferralsView(PortalView):
    @extend_schema(responses=s.PortalReferralsSerializer)
    def get(self, request: Request) -> Response:
        """The household's referral link, the families it referred and rewards earned."""
        household = self.client_household(request, "portal.client.refer")
        if services.active_program() is None:
            raise FeatureDisabled("referrals")
        client = household.clients[0] if household.clients else None
        if client is None:
            raise PermissionDenied()
        with transaction.atomic():
            code = services.code_for_client(client)
        board = selectors.referral_dashboard(household.client_ids)
        body = {
            "code": code.code,
            "link": _link(f"/?ref={code.code}"),
            "program": _program(board["program"]),
            "referrals": board["referrals"],
            "earned": board["earned"],
        }
        return Response(s.PortalReferralsSerializer(body).data)


class TutorReferralsPageView(APIView):
    permission_classes = [IsAuthenticated, HasOrganisation]

    @extend_schema(responses=s.TutorReferralsPageSerializer)
    def get(self, request: Request) -> Response:
        """A tutor's own referral code, share links and bonuses (FR-25-4)."""
        from tutortrack.sites.selectors import tutor_for_user

        tutor = tutor_for_user(request.user)
        if tutor is None or not has_perm(request.user, "growth.tutor_referral.view"):
            raise PermissionDenied()
        with transaction.atomic():
            code = services.code_for_tutor(tutor)
        rows = TutorReferral.objects.filter(referrer=tutor).order_by("-created_at")[:200]
        body = {
            "code": code.code,
            "client_link": _link(f"/?ref={code.code}"),
            "tutor_link": _link(f"/vacancies?ref={code.code}"),
            "referrals": [
                {
                    "id": r.pk,
                    "kind": r.kind,
                    "referred_name": selectors._first_word(r.referred_name),
                    "status": r.status,
                    "bonus": r.bonus.to_dict() if r.bonus else None,
                    "created_at": r.created_at,
                }
                for r in rows
            ],
        }
        return Response(s.TutorReferralsPageSerializer(body).data)


class AffiliatePortalView(APIView):
    permission_classes = [IsAuthenticated, HasOrganisation]

    def affiliate(self, request: Request, codename: str = "portal.affiliate.view") -> Affiliate:
        found = selectors.affiliate_for(request.user)
        if found is None or not has_perm(request.user, codename):
            raise PermissionDenied()
        return found


class AffiliateMeView(AffiliatePortalView):
    @extend_schema(responses=s.PortalAffiliateSerializer)
    def get(self, request: Request) -> Response:
        """The partner portal home: totals and tracking links."""
        from tutortrack.core.context import require_organisation_id
        from tutortrack.tenancy.models import Organisation

        affiliate = self.affiliate(request)
        org = Organisation.objects.get(pk=require_organisation_id())
        links = affiliate.links.filter(active=True).order_by("code")
        body = {
            "name": affiliate.name,
            "organisation": org.name,
            "payout_method": affiliate.payout_method,
            "bank_hint": affiliate.bank_hint,
            "summary": selectors.affiliate_summary(affiliate),
            "links": [
                {
                    "code": link.code,
                    "name": link.name,
                    "url": _link(f"{link.landing_path or '/'}?ref={link.code}"),
                    "clicks": link.clicks,
                }
                for link in links
            ],
        }
        return Response(s.PortalAffiliateSerializer(body).data)


class AffiliateClientsView(AffiliatePortalView):
    @extend_schema(responses=s.PortalAffiliateClientSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Referred clients, privacy-limited (shortened names, dates and commission)."""
        affiliate = self.affiliate(request)
        rows = selectors.portal_referred_clients(affiliate)
        return Response(s.PortalAffiliateClientSerializer(rows, many=True).data)


class AffiliateStatementsView(AffiliatePortalView):
    @extend_schema(responses=s.PortalStatementSerializer(many=True))
    def get(self, request: Request) -> Response:
        affiliate = self.affiliate(request)
        out = []
        for st in AffiliateStatement.objects.filter(affiliate=affiliate).prefetch_related("items")[
            :60
        ]:
            out.append(
                {
                    "id": st.pk,
                    "number": st.number,
                    "period_start": st.period_start,
                    "period_end": st.period_end,
                    "total": st.total.to_dict(),
                    "status": st.status,
                    "paid_at": st.paid_at,
                    "items": [
                        {
                            "kind": i.kind,
                            "description": i.description,
                            "amount": i.amount.to_dict(),
                            "earned_at": i.earned_at,
                        }
                        for i in st.items.all()
                    ],
                }
            )
        return Response(s.PortalStatementSerializer(out, many=True).data)


class AffiliatePayoutView(AffiliatePortalView):
    @extend_schema(request=s.PayoutDetailsSerializer, responses=s.PortalAffiliateSerializer)
    def put(self, request: Request) -> Response:
        """The affiliate's bank details for commission payouts (stored encrypted)."""
        affiliate = self.affiliate(request, "portal.affiliate.profile")
        payload = s.PayoutDetailsSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        services.update_payout_details(
            affiliate, bank=dict(d["bank"]), payee_name=d["payee_name"], country=d["country"]
        )
        return AffiliateMeView().get(request)

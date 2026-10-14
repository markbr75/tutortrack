from django.urls import path
from rest_framework.routers import SimpleRouter

from . import portal_views as pv
from . import public_views as pub
from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register("reviews", v.ReviewViewSet, basename="reviews")
router.register("review-requests", v.ReviewRequestViewSet, basename="review-requests")
router.register("referral-programs", v.ReferralProgramViewSet, basename="referral-programs")
router.register("referrals", v.ReferralViewSet, basename="referrals")
router.register("referral-codes", v.ReferralCodeViewSet, basename="referral-codes")
router.register("affiliates", v.AffiliateViewSet, basename="affiliates")
router.register("affiliate-links", v.AffiliateLinkViewSet, basename="affiliate-links")
router.register("affiliate-referrals", v.AffiliateReferralViewSet, basename="affiliate-referrals")
router.register("commission-rules", v.CommissionRuleViewSet, basename="commission-rules")
router.register("commission-items", v.CommissionItemViewSet, basename="commission-items")
router.register("affiliate-statements", v.StatementViewSet, basename="affiliate-statements")
router.register("tutor-referrals", v.TutorReferralViewSet, basename="tutor-referrals")

urlpatterns = [
    path("public/review/<str:token>", pub.PublicReviewView.as_view(), name="public-review"),
    path("public/ref", pub.PublicRefView.as_view(), name="public-ref"),
    path("portal/referrals", pv.PortalReferralsView.as_view(), name="portal-referrals"),
    path(
        "portal/tutor/referrals", pv.TutorReferralsPageView.as_view(), name="portal-tutor-referrals"
    ),
    path("portal/affiliate", pv.AffiliateMeView.as_view(), name="portal-affiliate"),
    path(
        "portal/affiliate/clients",
        pv.AffiliateClientsView.as_view(),
        name="portal-affiliate-clients",
    ),
    path(
        "portal/affiliate/statements",
        pv.AffiliateStatementsView.as_view(),
        name="portal-affiliate-statements",
    ),
    path(
        "portal/affiliate/payout", pv.AffiliatePayoutView.as_view(), name="portal-affiliate-payout"
    ),
    *router.urls,
]

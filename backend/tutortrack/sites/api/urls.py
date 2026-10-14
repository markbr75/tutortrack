from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v
from .mobile_views import PublicMobileAppView

router = SimpleRouter(trailing_slash=False)
router.register("brand-kits", v.BrandKitViewSet, basename="brand-kits")
router.register("domains", v.DomainViewSet, basename="domains")
router.register("widgets", v.WidgetViewSet, basename="widgets")
router.register("testimonials", v.TestimonialViewSet, basename="testimonials")
router.register("public-profiles", v.PublicProfileViewSet, basename="public-profiles")
router.register("sites/pages", v.SitePageViewSet, basename="site-pages")
router.register("sites/posts", v.BlogPostViewSet, basename="site-posts")
router.register("sites", v.SiteViewSet, basename="sites")

urlpatterns = [
    path("branding/options", v.BrandingOptionsView.as_view(), name="branding-options"),
    path("public-profiles/mine", v.MyPublicProfileView.as_view(), name="public-profile-mine"),
    path("sites/themes", v.SiteThemesView.as_view(), name="site-themes"),
    path("sites/blocks", v.SiteBlocksView.as_view(), name="site-blocks"),
    path("public/branding", v.PublicBrandingView.as_view(), name="public-branding"),
    path("public/manifest", v.PublicManifestView.as_view(), name="public-manifest"),
    path("public/mobile-app", PublicMobileAppView.as_view(), name="public-mobile-app"),
    path("public/tutors", v.PublicTutorsView.as_view(), name="public-tutors"),
    path("public/tutors/<slug:slug>", v.PublicTutorView.as_view(), name="public-tutor"),
    path("public/services", v.PublicServicesView.as_view(), name="public-services"),
    path("public/reviews", v.PublicReviewsView.as_view(), name="public-reviews"),
    path("public/widgets/<slug:key>", v.PublicWidgetView.as_view(), name="public-widget"),
    path("public/assets/<uuid:file_id>", v.PublicAssetView.as_view(), name="public-asset"),
    *router.urls,
]

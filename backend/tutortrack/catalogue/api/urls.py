from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("catalogue/categories", views.CategoryViewSet, basename="categories")
router.register("catalogue/subjects", views.SubjectViewSet, basename="subjects")
router.register("catalogue/levels", views.LevelViewSet, basename="levels")
router.register("catalogue/tax-rates", views.TaxRateViewSet, basename="tax-rates")
router.register("catalogue/services", views.ServiceViewSet, basename="services")
router.register("catalogue/locations", views.LocationViewSet, basename="locations")
router.register("catalogue/products", views.ProductViewSet, basename="products")
router.register("catalogue/packages", views.PackageTemplateViewSet, basename="packages")
router.register("catalogue/rooms", views.RoomViewSet, basename="rooms")
router.register("catalogue/pay-tiers", views.PayTierViewSet, basename="pay-tiers")
router.register(
    "catalogue/tier-assignments", views.TierAssignmentViewSet, basename="tier-assignments"
)
router.register("catalogue/tutor-rates", views.TutorRateViewSet, basename="tutor-rates")
router.register(
    "catalogue/holiday-calendars", views.HolidayCalendarViewSet, basename="holiday-calendars"
)
router.register("catalogue/holidays", views.HolidayViewSet, basename="holidays")
router.register("catalogue/premiums", views.PremiumRuleViewSet, basename="premiums")
router.register("catalogue/discounts", views.DiscountRuleViewSet, basename="discounts")
router.register("catalogue/promo-codes", views.PromoCodeViewSet, basename="promo-codes")
router.register("catalogue/price-lists", views.PriceListViewSet, basename="price-lists")

urlpatterns = [
    path("rates/quote", views.QuoteView.as_view(), name="rates-quote"),
    path("catalogue/tier-rates", views.TierRatesView.as_view(), name="tier-rates"),
    path("catalogue/tier-rates/csv", views.TierRatesCsvView.as_view(), name="tier-rates-csv"),
    *router.urls,
]

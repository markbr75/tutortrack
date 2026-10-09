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

urlpatterns = [
    path("rates/quote", views.QuoteView.as_view(), name="rates-quote"),
    *router.urls,
]

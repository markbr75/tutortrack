from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import ConsentRecordViewSet, ConsentTypeViewSet, MyConsentsView

router = SimpleRouter(trailing_slash=False)
router.register("consent-types", ConsentTypeViewSet, basename="consent-types")
router.register("consents", ConsentRecordViewSet, basename="consents")

urlpatterns = [path("me/consents", MyConsentsView.as_view(), name="me-consents"), *router.urls]

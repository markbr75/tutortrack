from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register(
    "accounting/connections", v.AccountingConnectionViewSet, basename="accounting-connections"
)
router.register("accounting/records", v.ExternalRecordViewSet, basename="accounting-records")

urlpatterns = [
    path(
        "accounting/mappings/<str:provider>",
        v.MappingSetView.as_view(),
        name="accounting-mappings",
    ),
    path("accounting/export", v.ExportView.as_view(), name="accounting-export"),
    *router.urls,
]

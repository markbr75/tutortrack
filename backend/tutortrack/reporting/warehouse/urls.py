from django.urls import path
from rest_framework.routers import SimpleRouter

from . import api

router = SimpleRouter(trailing_slash=False)
router.register(
    "reporting/warehouse/destinations",
    api.WarehouseDestinationViewSet,
    basename="warehouse-destinations",
)

urlpatterns = [
    path("reporting/warehouse/schema", api.WarehouseSchemaView.as_view(), name="warehouse-schema"),
    path(
        "reporting/warehouse/exports/<uuid:pk>/download",
        api.WarehouseDownloadView.as_view(),
        name="warehouse-download",
    ),
    *router.urls,
]

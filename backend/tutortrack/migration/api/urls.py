from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register("imports", v.ImportBatchViewSet, basename="imports")
router.register("import-mappings", v.SavedImportMappingViewSet, basename="import-mappings")
router.register("migration-projects", v.MigrationProjectViewSet, basename="migration-projects")
router.register("data-exports", v.ExportJobViewSet, basename="data-exports")

urlpatterns = [
    path("import-catalogue", v.ImportCatalogueView.as_view(), name="import-catalogue"),
    path(
        "import-templates/<slug:entity>",
        v.ImportTemplateView.as_view(),
        name="import-template",
    ),
    *router.urls,
]

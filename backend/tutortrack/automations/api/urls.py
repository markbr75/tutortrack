from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register("automations", v.AutomationViewSet, basename="automations")
router.register("automation-runs", v.AutomationRunViewSet, basename="automation-runs")

urlpatterns = [
    path("automation-schema", v.AutomationSchemaView.as_view(), name="automation-schema"),
    path("automation-recipes", v.RecipesView.as_view(), name="automation-recipes"),
    path(
        "automation-recipes/<slug:key>/install",
        v.RecipeInstallView.as_view(),
        name="automation-recipe-install",
    ),
    *router.urls,
]

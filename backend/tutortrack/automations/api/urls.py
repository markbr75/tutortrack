from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register("automations", v.AutomationViewSet, basename="automations")
router.register("automation-runs", v.AutomationRunViewSet, basename="automation-runs")
# E33: the product calls them workflows; /automations stays for one release.
router.register("workflows", v.AutomationViewSet, basename="workflows")
router.register("workflow-runs", v.AutomationRunViewSet, basename="workflow-runs")

urlpatterns = [
    path("automation-schema", v.AutomationSchemaView.as_view(), name="automation-schema"),
    path("workflow-schema", v.WorkflowSchemaView.as_view(), name="workflow-schema"),
    path("automation-recipes", v.RecipesView.as_view(), name="automation-recipes"),
    path(
        "automation-recipes/<slug:key>/install",
        v.RecipeInstallView.as_view(),
        name="automation-recipe-install",
    ),
    *router.urls,
]

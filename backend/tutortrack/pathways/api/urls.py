from django.urls import path, re_path
from rest_framework.routers import SimpleRouter

from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register("pathway-templates", v.PathwayTemplateViewSet, basename="pathway-templates")
router.register("pathway-runs", v.PathwayRunViewSet, basename="pathway-runs")

urlpatterns = [
    path("pathway-schema", v.PathwaySchemaView.as_view(), name="pathway-schema"),
    re_path(
        r"^pathway-runs/(?P<pk>[0-9a-f-]{36})/steps/(?P<key>[a-z][a-z0-9_]{0,39})/"
        r"(?P<act>complete|skip|reject|remind)$",
        v.PathwayStepActionView.as_view(),
        name="pathway-step-action",
    ),
    path("me/tasks", v.MyPathwayTasksView.as_view(), name="my-pathway-tasks"),
    path(
        "me/tasks/<uuid:pk>/complete",
        v.MyPathwayTaskCompleteView.as_view(),
        name="my-pathway-task-complete",
    ),
    *router.urls,
]

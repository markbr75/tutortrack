from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("custom-fields", views.CustomFieldViewSet, basename="custom-fields")
router.register("tags", views.TagViewSet, basename="tags")
router.register("notes", views.NoteViewSet, basename="notes")
router.register("tasks", views.TaskViewSet, basename="tasks")
router.register("documents", views.DocumentViewSet, basename="documents")
router.register("saved-views", views.SavedViewViewSet, basename="saved-views")
router.register("bulk-jobs", views.BulkJobViewSet, basename="bulk-jobs")

urlpatterns = [
    path("timeline", views.TimelineView.as_view(), name="timeline"),
    path("search", views.SearchView.as_view(), name="search"),
    path("bulk/<slug:entity>/<slug:bulk_action>", views.BulkView.as_view(), name="bulk"),
    *router.urls,
]

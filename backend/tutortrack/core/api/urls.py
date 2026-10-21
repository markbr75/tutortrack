from django.urls import path
from rest_framework.routers import SimpleRouter

from .public_uploads import PublicUploadCompleteView, PublicUploadView
from .views import AuditEntryViewSet, FeaturesView, PlatformStatusView, StoredFileViewSet

router = SimpleRouter(trailing_slash=False)
router.register("audit", AuditEntryViewSet, basename="audit")
router.register("files", StoredFileViewSet, basename="files")

urlpatterns = [
    path("features", FeaturesView.as_view(), name="features"),
    path("status", PlatformStatusView.as_view(), name="platform-status"),
    path("public/uploads", PublicUploadView.as_view(), name="public-uploads"),
    path(
        "public/uploads/complete", PublicUploadCompleteView.as_view(), name="public-upload-complete"
    ),
    *router.urls,
]

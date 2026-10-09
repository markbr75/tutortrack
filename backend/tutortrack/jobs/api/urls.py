from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("jobs", views.JobViewSet, basename="jobs")

urlpatterns = router.urls

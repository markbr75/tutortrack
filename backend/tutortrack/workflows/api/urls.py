from rest_framework.routers import SimpleRouter

from .views import ProcessViewSet

router = SimpleRouter(trailing_slash=False)
router.register("processes", ProcessViewSet, basename="processes")

urlpatterns = router.urls

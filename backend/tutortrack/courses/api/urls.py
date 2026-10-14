from django.urls import path
from rest_framework.routers import SimpleRouter

from . import portal_views as pv
from . import public_views as pub
from . import views as v

router = SimpleRouter(trailing_slash=False)
router.register("academic-years", v.AcademicYearViewSet, basename="academic-years")
router.register("terms", v.TermViewSet, basename="terms")
router.register("courses", v.CourseViewSet, basename="courses")
router.register("classes", v.GroupClassViewSet, basename="classes")
router.register("class-sessions", v.SessionViewSet, basename="class-sessions")
router.register("class-makeups", v.MakeupViewSet, basename="class-makeups")
# Before "enrolments": its detail route would otherwise take "rollover" as an id.
router.register("enrolments/rollover", v.RolloverViewSet, basename="enrolment-rollovers")
router.register("enrolments", v.EnrolmentViewSet, basename="enrolments")

urlpatterns = [
    path("public/catalogue", pub.PublicCatalogueView.as_view(), name="public-catalogue"),
    path("public/enrol", pub.PublicEnrolView.as_view(), name="public-enrol"),
    path(
        "public/enrolments/<uuid:enrolment_id>",
        pub.PublicEnrolmentStatusView.as_view(),
        name="public-enrolment",
    ),
    path("public/re-enrol/<str:token>", pub.PublicRolloverView.as_view(), name="public-re-enrol"),
    path("portal/classes", pv.PortalCatalogueView.as_view(), name="portal-classes"),
    path("portal/courses", pv.PortalCoursesView.as_view(), name="portal-courses"),
    path("portal/enrol", pv.PortalEnrolView.as_view(), name="portal-enrol"),
    path(
        "portal/enrolments/<uuid:enrolment_id>/cancel",
        pv.PortalEnrolmentCancelView.as_view(),
        name="portal-enrolment-cancel",
    ),
    path(
        "portal/rollover-offers/<uuid:offer_id>",
        pv.PortalRolloverAnswerView.as_view(),
        name="portal-rollover-answer",
    ),
    *router.urls,
]

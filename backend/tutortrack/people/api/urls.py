from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    ClientContactViewSet,
    ClientViewSet,
    ContactViewSet,
    DuplicatePairsView,
    DuplicatesView,
    MergePreviewView,
    MergeView,
    PeopleMapGeocodeView,
    PeopleMapView,
    StudentViewSet,
    TutorViewSet,
)

router = SimpleRouter(trailing_slash=False)
router.register("clients", ClientViewSet, basename="clients")
router.register("contacts", ContactViewSet, basename="contacts")
router.register("students", StudentViewSet, basename="students")
router.register("tutors", TutorViewSet, basename="tutors")

client_contacts = ClientContactViewSet.as_view({"get": "list", "post": "create"})

urlpatterns = [
    path("clients/<uuid:client_id>/contacts", client_contacts, name="client-contacts"),
    path("people/duplicates", DuplicatesView.as_view(), name="people-duplicates"),
    path("people/duplicates/pairs", DuplicatePairsView.as_view(), name="people-duplicate-pairs"),
    path("merge/<slug:entity>", MergeView.as_view(), name="merge"),
    path("merge/<slug:entity>/preview", MergePreviewView.as_view(), name="merge-preview"),
    path("people/map", PeopleMapView.as_view(), name="people-map"),
    path("people/map/geocode", PeopleMapGeocodeView.as_view(), name="people-map-geocode"),
    *router.urls,
]

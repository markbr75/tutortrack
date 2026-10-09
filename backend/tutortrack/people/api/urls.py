from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    ClientContactViewSet,
    ClientViewSet,
    ContactViewSet,
    DuplicatesView,
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
    *router.urls,
]

"""People as consent subjects (E29 FR-29-3)."""

from collections.abc import Callable

from tutortrack.privacy import subjects


def _exists(model_name: str) -> Callable[[str], bool]:
    def check(subject_id: str) -> bool:
        from django.apps import apps

        model = apps.get_model("people", model_name)
        try:
            return bool(model.objects.filter(pk=subject_id).exists())
        except (ValueError, Exception):
            return False

    return check


subjects.register("people.client", _exists("Client"))
subjects.register("people.contact", _exists("Contact"))
subjects.register("people.student", _exists("Student"))

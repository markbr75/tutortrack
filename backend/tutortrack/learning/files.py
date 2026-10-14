"""Who may open learning files (``core.storage`` access rules): resource files, homework
attachments and submitted work. Staff and tutors through their learning scopes; families
through their household (shares and their own students' homework)."""

from __future__ import annotations

from typing import Any

from tutortrack.core.models import StoredFile
from tutortrack.core.storage.services import register_access_rule

from . import selectors


def _household(user: Any) -> Any:
    from tutortrack.portal.household import household_for

    return household_for(user)


def _resource(user: Any, stored: StoredFile) -> bool:
    pk = stored.owner_object_id
    if selectors.resources(user).filter(pk=pk).exists():
        return True
    household = _household(user)
    return household is not None and selectors.household_resources(household).filter(pk=pk).exists()


def _homework(user: Any, stored: StoredFile) -> bool:
    pk = stored.owner_object_id
    if selectors.homework(user).filter(pk=pk).exists():
        return True
    household = _household(user)
    return (
        household is not None
        and selectors.household_assignments(household).filter(homework_id=pk).exists()
    )


def _submission(user: Any, stored: StoredFile) -> bool:
    from .models import HomeworkSubmission

    submission = HomeworkSubmission.objects.filter(pk=stored.owner_object_id).first()
    if submission is None:
        return False
    if selectors.assignments(user).filter(pk=submission.assignment_id).exists():
        return True
    household = _household(user)
    return (
        household is not None
        and selectors.household_assignments(household).filter(pk=submission.assignment_id).exists()
    )


register_access_rule("learning.resource", _resource)
register_access_rule("learning.homework", _homework)
register_access_rule("learning.homeworksubmission", _submission)

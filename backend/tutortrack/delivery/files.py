"""Who may open files attached to lesson reports (``core.storage`` access rules, gap G3).

Staff and tutors who can see the report (``selectors.reports``); families when the report
has been shared with them and the file sits in an answer their audience may see (client
or student visibility, FR-09-4).
"""

from __future__ import annotations

from typing import Any

from tutortrack.core.models import StoredFile
from tutortrack.core.storage.services import register_access_rule

from . import selectors, templates


def _report_file(user: Any, stored: StoredFile) -> bool:
    if selectors.reports(user).filter(pk=stored.owner_object_id).exists():
        return True
    from tutortrack.portal.household import household_for
    from tutortrack.portal.selectors import shared_reports

    household = household_for(user)
    if household is None:
        return False
    report = shared_reports(household).filter(pk=stored.owner_object_id).first()
    if report is None:
        return False
    audience = "client" if household.is_client else "student"
    visible = templates.visible_answers(
        report.template_version.fields, report.answers or {}, audience
    )
    return any(
        str(stored.pk) in [str(v) for v in value]
        for value in visible.values()
        if isinstance(value, list)
    )


register_access_rule("delivery.lessonreport", _report_file)

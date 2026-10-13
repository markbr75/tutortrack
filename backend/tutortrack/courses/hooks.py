"""What courses plugs into other apps at start-up (E20-T01, T04, T09):

* E10 termly billing plans follow the branch's term dates;
* E08 series skip term breaks (class sessions always; other lessons by setting);
* E24 serves public course images.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from tutortrack.billing import plans
from tutortrack.scheduling import services as scheduling
from tutortrack.sites import selectors as sites

from . import selectors


def term_calendar(branch_id: Any) -> list[tuple[date, date]]:
    return selectors.term_dates(branch_id)


def break_skips(series: Any, start: date, end: date) -> set[date]:
    from tutortrack.tenancy.settings_service import get_setting

    is_class = bool((series.template or {}).get("group_class"))
    if not is_class and not get_setting("courses.breaks_skip_all_lessons"):
        return set()
    return selectors.break_dates(series.branch_id, start, end)


plans.register_term_calendar(term_calendar)
scheduling.register_skip_dates(break_skips)
sites.register_public_assets(selectors.public_course_images)

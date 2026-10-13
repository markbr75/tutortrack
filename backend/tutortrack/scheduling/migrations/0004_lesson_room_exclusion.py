"""E08-T12: no two non-cancelled lessons in one room at the same time (FR-08-6).

Expand/contract: 0003 added the nullable ``room`` column (existing lessons have none), so
the constraint holds for every existing row and needs no backfill. ``btree_gist`` lets the
GiST index combine ``room_id =`` with ``tstzrange &&``; it is a trusted extension, so the
table owner can create it.
"""

import django.contrib.postgres.constraints
from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations, models

import tutortrack.scheduling.models


class Migration(migrations.Migration):
    dependencies = [
        ("scheduling", "0003_rooms_reschedule_booking"),
    ]

    operations = [
        BtreeGistExtension(),
        migrations.AddConstraint(
            model_name="lesson",
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                condition=models.Q(
                    ("room__isnull", False), models.Q(("status", "cancelled"), _negated=True)
                ),
                expressions=[
                    ("room", "="),
                    (
                        tutortrack.scheduling.models.TsTzRange(
                            "start", "end", models.Value("[)")
                        ),
                        "&&",
                    ),
                ],
                name="lesson_room_no_overlap",
            ),
        ),
    ]

"""Privacy and safeguarding settings (E29 Part 2). ``privacy.closure_grace_days`` is
registered by tenancy (E02) in the same area."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

# --- data subject requests, erasure and retention (FR-29-4, FR-29-5) ---------------------------
register(
    "privacy.dsar_deadline_days",
    type="int",
    default=30,
    min_value=1,
    max_value=90,
    label=_("Days to answer a data subject request"),
)
register(
    "privacy.dsar_link_days",
    type="int",
    default=7,
    min_value=1,
    max_value=30,
    label=_("Days a data export download link stays valid"),
)
register(
    "privacy.financial_retention_years",
    type="int",
    default=6,
    min_value=1,
    max_value=12,
    label=_("Years financial records keep the bill payer's details"),
    help_text=_("6 years in the UK; some countries require 7 or more."),
)
register(
    "privacy.retention_purge",
    type="choice",
    default="off",
    choices=(
        ("off", _("Off")),
        ("dry_run", _("Nightly report only (dry run)")),
        ("on", _("Nightly purge")),
    ),
    label=_("Nightly retention purge"),
)

# --- children's privacy (FR-29-7) ---------------------------------------------------------------
register(
    "privacy.coppa",
    type="choice",
    default="auto",
    choices=(
        ("auto", _("When the organisation is in the US")),
        ("on", _("Always")),
        ("off", _("Never")),
    ),
    label=_("Require verifiable parental consent before under-13s get a login (COPPA)"),
)
register(
    "privacy.child_defaults",
    type="bool",
    default=True,
    label=_("High-privacy defaults for under-18s (no marketing, no profiling)"),
    help_text=_("The UK Age Appropriate Design Code."),
)

# --- safeguarding (FR-29-6) ---------------------------------------------------------------------
register(
    "safeguarding.block_tutor_student_direct",
    type="bool",
    default=True,
    label=_("Tutors can't message students under 18 directly"),
)
register(
    "safeguarding.require_parent_on_threads",
    type="bool",
    default=True,
    label=_("A parent must be on every conversation with a student under 18"),
)
register(
    "safeguarding.contact_details",
    type="choice",
    default="block",
    choices=(
        ("off", _("Allow")),
        ("flag", _("Allow but flag for review")),
        ("block", _("Block and flag for review")),
    ),
    label=_("Personal contact details (phone numbers, emails, social handles) in messages"),
)
register(
    "safeguarding.flag_keywords",
    type="str",
    default="meet up,our secret,don't tell,dont tell,delete this,snapchat,whatsapp me,"
    "come alone,send a photo,hurt myself,kill myself",
    max_length=2000,
    label=_("Words and phrases that flag a message for review (comma-separated)"),
)
register(
    "safeguarding.lone_working",
    type="choice",
    default="off",
    choices=(
        ("off", _("Off")),
        ("client_homes", _("Lessons at a client's home")),
        ("in_person", _("All in-person lessons")),
    ),
    label=_("Lone-working check-in and check-out"),
)
register(
    "safeguarding.lone_working_grace_minutes",
    type="int",
    default=30,
    min_value=5,
    max_value=240,
    label=_("Alert when a tutor hasn't checked out this many minutes after the lesson"),
)
register(
    "safeguarding.lone_working_escalate_minutes",
    type="int",
    default=30,
    min_value=5,
    max_value=240,
    label=_("Escalate to safeguarding leads this many minutes after the first alert"),
)

"""Platform default templates (en). Organisations override them per channel (FR-13-3).

``{{ ... }}`` is Jinja2 (sandboxed). Filters: ``|datetime("short")``, ``|time``, ``|date``,
``|money``. Times show in the lesson's (or the organisation's) timezone.
"""

from __future__ import annotations

WHEN = '{{ lesson.start|datetime("full") }}'
WHERE = (
    "{% if lesson.online %}Online{% if lesson.meeting_url %}: {{ lesson.meeting_url }}"
    "{% endif %}{% elif lesson.location %}{{ lesson.location }}{% endif %}"
)
SIGN = "\n\n{{ organisation.name }}"

DEFAULTS: dict[tuple[str, str], tuple[str, str]] = {
    ("lesson_booked", "email"): (
        "Lesson booked: {{ lesson.title }}",
        "Hello {{ recipient.first_name }},\n\n{{ lesson.title }} is booked for "
        + WHEN
        + " with {{ lesson.tutor_names }}.\n"
        + WHERE
        + SIGN,
    ),
    ("lesson_booked", "sms"): (
        "",
        "{{ organisation.name }}: {{ lesson.title }} booked for "
        '{{ lesson.start|datetime("short") }}.',
    ),
    ("lesson_booked", "in_app"): ("Lesson booked", "{{ lesson.title }}, " + WHEN),
    ("lesson_changed", "email"): (
        "Lesson moved: {{ lesson.title }}",
        "Hello {{ recipient.first_name }},\n\n{{ lesson.title }} has moved to "
        + WHEN
        + ".\n"
        + WHERE
        + SIGN,
    ),
    ("lesson_changed", "sms"): (
        "",
        "{{ organisation.name }}: {{ lesson.title }} moved to "
        '{{ lesson.start|datetime("short") }}.',
    ),
    ("lesson_changed", "in_app"): ("Lesson moved", "{{ lesson.title }}, now " + WHEN),
    ("lesson_cancelled", "email"): (
        "Lesson cancelled: {{ lesson.title }}",
        "Hello {{ recipient.first_name }},\n\n{{ lesson.title }} on "
        + WHEN
        + " has been cancelled.{% if lesson.status_reason %}\nReason: "
        "{{ lesson.status_reason }}{% endif %}" + SIGN,
    ),
    ("lesson_cancelled", "sms"): (
        "",
        "{{ organisation.name }}: {{ lesson.title }} on "
        '{{ lesson.start|datetime("short") }} is cancelled.',
    ),
    ("lesson_cancelled", "in_app"): ("Lesson cancelled", "{{ lesson.title }}, " + WHEN),
    ("lesson_reminder", "email"): (
        'Reminder: {{ lesson.title }} {{ lesson.start|datetime("short") }}',
        "Hello {{ recipient.first_name }},\n\nA reminder that {{ lesson.title }} is on "
        + WHEN
        + ".\n"
        + WHERE
        + SIGN,
    ),
    ("lesson_reminder", "sms"): (
        "",
        "Reminder from {{ organisation.name }}: {{ lesson.title }} "
        '{{ lesson.start|datetime("short") }}.',
    ),
    ("lesson_reminder", "in_app"): ("Lesson soon", "{{ lesson.title }}, " + WHEN),
    ("series_created", "email"): (
        "Your regular lessons: {{ lesson.service }}",
        "Hello {{ recipient.first_name }},\n\nRegular lessons are arranged with "
        "{{ lesson.tutor_names }}. The next ones are:\n"
        '{% for item in upcoming %}- {{ item.start|datetime("full") }}\n{% endfor %}' + SIGN,
    ),
    ("tutor_assigned", "email"): (
        "New job: {{ job.name }}",
        "Hello {{ recipient.first_name }},\n\nYou've been assigned to {{ job.name }} "
        "({{ job.reference }}, {{ job.service }})." + SIGN,
    ),
    ("tutor_assigned", "in_app"): ("New job", "{{ job.name }} ({{ job.reference }})"),
    ("report_shared", "email"): (
        "Lesson report: {{ report.lesson_title }}",
        "Hello {{ recipient.first_name }},\n\n{{ report.tutor_name }} wrote a report on "
        '{{ report.lesson_title }} ({{ report.lesson_start|datetime("medium") }}).\n\n'
        "{% for row in report.answers %}{{ row.label }}:\n{{ row.value }}\n\n{% endfor %}"
        + SIGN.strip("\n"),
    ),
    ("report_due", "email"): (
        "Report due: {{ report.lesson_title }}",
        "Hello {{ recipient.first_name }},\n\nYour report for {{ report.lesson_title }} is "
        'due by {{ report.due_at|datetime("short") }}.\nWrite it here: {{ report.link }}' + SIGN,
    ),
    ("report_due", "sms"): (
        "",
        'Report due by {{ report.due_at|datetime("short") }}: {{ report.lesson_title }}. '
        "{{ report.link }}",
    ),
    ("report_due", "in_app"): ("Report due", "{{ report.lesson_title }}"),
    ("report_overdue", "email"): (
        "Report overdue: {{ report.lesson_title }}",
        "Hello {{ recipient.first_name }},\n\nYour report for {{ report.lesson_title }} is "
        "overdue. Please write it now: {{ report.link }}" + SIGN,
    ),
    ("report_overdue", "sms"): ("", "Report overdue: {{ report.lesson_title }}. {{ report.link }}"),
    ("report_overdue", "in_app"): ("Report overdue", "{{ report.lesson_title }}"),
    ("lesson_unconfirmed", "email"): (
        "Please confirm: {{ lesson.title }}",
        "Hello {{ recipient.first_name }},\n\n{{ lesson.title }} on "
        + WHEN
        + " hasn't been marked as completed or cancelled yet. Please update it."
        + SIGN,
    ),
    ("lesson_unconfirmed", "sms"): (
        "",
        'Please mark {{ lesson.title }} ({{ lesson.start|datetime("short") }}) as '
        "completed or cancelled.",
    ),
    ("lesson_unconfirmed", "in_app"): ("Lesson not confirmed", "{{ lesson.title }}, " + WHEN),
    ("invoice_issued", "email"): (
        "Invoice {{ invoice.number }} from {{ organisation.name }}",
        "Hello {{ recipient.first_name }},\n\nPlease find invoice {{ invoice.number }} "
        "attached.\nAmount due: {{ invoice.balance_due|money }} by "
        "{{ invoice.due_date|date }}.\n{% if invoice.pay_url %}Pay online: {{ invoice.pay_url }}"
        "{% endif %}" + SIGN,
    ),
    ("invoice_reminder", "email"): (
        "{% if days_overdue %}Overdue{% else %}Reminder{% endif %}: invoice {{ invoice.number }}",
        "Hello {{ recipient.first_name }},\n\nInvoice {{ invoice.number }} for "
        "{{ invoice.balance_due|money }} {% if days_overdue %}was due on{% else %}is due on"
        "{% endif %} {{ invoice.due_date|date }}.\n{% if invoice.pay_url %}Pay online: "
        "{{ invoice.pay_url }}{% endif %}" + SIGN,
    ),
    ("invoice_reminder", "sms"): (
        "",
        "{{ organisation.name }}: invoice {{ invoice.number }} for "
        "{{ invoice.balance_due|money }} is due {{ invoice.due_date|date }}. {{ invoice.pay_url }}",
    ),
    ("payment_received", "email"): (
        "Payment received \N{EN DASH} thank you",
        "Hello {{ recipient.first_name }},\n\nWe received your payment of "
        "{{ payment.amount|money }}. Your receipt is attached." + SIGN,
    ),
    ("payment_failed", "email"): (
        "Payment for invoice {{ invoice.number }} didn't go through",
        "Hello {{ recipient.first_name }},\n\nWe couldn't take the automatic payment for "
        "invoice {{ invoice.number }} ({{ invoice.balance_due|money }}). Please pay online: "
        "{{ invoice.pay_url }}" + SIGN,
    ),
    ("payment_failed", "sms"): (
        "",
        "{{ organisation.name }}: the payment for {{ invoice.number }} failed. Please pay: "
        "{{ invoice.pay_url }}",
    ),
    ("payment_request", "email"): (
        "Payment request {{ request.number }}",
        "Hello {{ recipient.first_name }},\n\n{{ request.description }}: "
        "{{ request.amount|money }}.\nPay online: {{ request.pay_url }}" + SIGN,
    ),
    ("payment_request", "sms"): (
        "",
        "{{ organisation.name }}: please top up {{ request.amount|money }}. {{ request.pay_url }}",
    ),
    ("balance_low", "email"): (
        "Your credit is running low",
        "Hello {{ recipient.first_name }},\n\nYou have {{ available|money }} of credit left. "
        "Please top up to keep lessons going." + SIGN,
    ),
    ("balance_low", "sms"): (
        "",
        "{{ organisation.name }}: your credit is low ({{ available|money }}).",
    ),
    ("task_assigned", "in_app"): ("Task assigned to you", "{{ task.title }}"),
    ("task_assigned", "email"): (
        "Task: {{ task.title }}",
        "Hello {{ recipient.first_name }},\n\nYou have a new task: {{ task.title }}." + SIGN,
    ),
}

DEFAULTS[("absence_notified", "email")] = (
    "{{ absence.student }} will miss {{ lesson.title }}",
    "Hello {{ recipient.first_name }},\n\n{{ absence.student }} won't be at {{ lesson.title }} on "
    + WHEN
    + ".{% if absence.note %}\nNote: {{ absence.note }}{% endif %}"
    + SIGN,
)
DEFAULTS[("absence_notified", "in_app")] = (
    "{{ absence.student }} will be absent",
    "{{ lesson.title }}, " + WHEN,
)
DEFAULTS[("report_comment", "email")] = (
    "Reply to your report: {{ report.lesson_title }}",
    "Hello {{ recipient.first_name }},\n\n{{ comment.author }} replied:\n{{ comment.body }}\n\n"
    "{{ report.link }}" + SIGN,
)
DEFAULTS[("report_comment", "in_app")] = ("Reply from {{ comment.author }}", "{{ comment.body }}")

for _key in (
    "staff_profile_change",
    "staff_report_escalated",
    "staff_completion_blocked",
    "staff_payment_failed",
    "staff_dispute",
    "subscription_notice",
    "staff_support_access",
    "staff_expense_submitted",
    "staff_pay_run_review",
    "staff_payout_failed",
    "staff_enquiry_sla",
    "staff_compliance_submitted",
    "staff_compliance_expiring",
    "staff_application_waiting",
    "staff_offer_accepted",
    "staff_offers_exhausted",
    "staff_job_application",
    "staff_cover_unfilled",
):
    DEFAULTS[(_key, "in_app")] = ("{{ alert.title }}", "{{ alert.body }}")
    DEFAULTS[(_key, "email")] = ("{{ alert.title }}", "{{ alert.body }}" + SIGN)


DEFAULTS[("enquiry_acknowledgement", "email")] = (
    "Thanks for getting in touch",
    "Hello {{ recipient.first_name }},\n\nThank you for your enquiry. We've received it and "
    "will be in touch soon." + SIGN,
)
DEFAULTS[("enquiry_acknowledgement", "sms")] = (
    "",
    "{{ organisation.name }}: thanks for your enquiry, we'll be in touch soon.",
)
DEFAULTS[("enquiry_assigned", "in_app")] = (
    "New enquiry: {{ enquiry.title }}",
    "From {{ enquiry.source }}",
)
DEFAULTS[("enquiry_assigned", "email")] = (
    "New enquiry: {{ enquiry.title }}",
    "A new enquiry has been assigned to you ({{ enquiry.source }})." + SIGN,
)
DEFAULTS[("waitlist_offer", "email")] = (
    "A place is available for {{ offer.student }}",
    "Hello {{ recipient.first_name }},\n\nA place has come up for {{ offer.student }}"
    "{% if offer.subject %} ({{ offer.subject }}){% endif %}: {{ offer.details }}\n\n"
    "Accept or decline here: {{ offer.link }}"
    '{% if offer.expires_at %}\nThe offer is held until {{ offer.expires_at|datetime("short") }}.'
    "{% endif %}" + SIGN,
)
DEFAULTS[("waitlist_offer", "sms")] = (
    "",
    "{{ organisation.name }}: a place is available for {{ offer.student }}. Reply here: "
    "{{ offer.link }}",
)


DEFAULTS[("interview_invite", "email")] = (
    "Interview with {{ organisation.name }}",
    "Hello {{ recipient.first_name }},\n\nThank you for applying. Please choose a time for a "
    "{{ interview.minutes }}-minute interview: {{ interview.link }}" + SIGN,
)
DEFAULTS[("reference_request", "email")] = (
    "Reference for {{ reference.applicant }}",
    "Hello {{ recipient.first_name }},\n\n{{ reference.applicant }} has applied to tutor with "
    "us and gave your name as a referee. Please give a short reference here: "
    "{{ reference.link }}" + SIGN,
)
DEFAULTS[("reference_reminder", "email")] = (
    "Reminder: reference for {{ reference.applicant }}",
    "Hello {{ recipient.first_name }},\n\nA reminder that we'd be grateful for your reference "
    "for {{ reference.applicant }}. Please use the link in our first email." + SIGN,
)
DEFAULTS[("application_rejected", "email")] = (
    "Your application to {{ organisation.name }}",
    "Hello {{ recipient.first_name }},\n\nThank you for applying. We won't be taking your "
    "application further this time, but we wish you well." + SIGN,
)
DEFAULTS[("compliance_reminder", "email")] = (
    "{{ check.name }} expires soon",
    "Hello {{ recipient.first_name }},\n\nYour {{ check.name }} expires in {{ check.days }} "
    "days. Please upload the renewal in the tutor portal so you can keep teaching." + SIGN,
)
DEFAULTS[("compliance_reminder", "in_app")] = (
    "{{ check.name }} expires in {{ check.days }} days",
    "Upload the renewal in your profile.",
)
DEFAULTS[("onboarding_reminder", "email")] = (
    "Finish setting up with {{ organisation.name }}",
    "Hello {{ recipient.first_name }},\n\nThere are still a few onboarding steps to finish "
    "in the tutor portal before you can start." + SIGN,
)
DEFAULTS[("onboarding_reminder", "in_app")] = (
    "Finish your onboarding",
    "A few steps are left before you can start.",
)


DEFAULTS[("job_offer", "email")] = (
    "Job offer: {{ offer.brief }}",
    "Hello {{ recipient.first_name }},\n\nWe'd like to offer you a new job: {{ offer.brief }}."
    "\n\nAccept or decline in the tutor portal: {{ offer.link }}"
    '{% if offer.expires_at %}\nPlease answer by {{ offer.expires_at|datetime("short") }}.'
    "{% endif %}" + SIGN,
)
DEFAULTS[("job_offer", "sms")] = (
    "",
    "{{ organisation.name }}: new job offer ({{ offer.brief }}). Answer here: {{ offer.link }}",
)
DEFAULTS[("job_offer", "in_app")] = ("New job offer", "{{ offer.brief }}")
DEFAULTS[("job_offer_withdrawn", "email")] = (
    "Job offer withdrawn",
    "Hello {{ recipient.first_name }},\n\nThe offer for {{ offer.brief }} has been withdrawn: "
    "{{ offer.reason }}. Thank you for your interest." + SIGN,
)
DEFAULTS[("job_offer_withdrawn", "in_app")] = ("Job offer withdrawn", "{{ offer.brief }}")
DEFAULTS[("job_intro_tutor", "email")] = (
    "Your new job: {{ job.name }}",
    "Hello {{ recipient.first_name }},\n\nYou're now the tutor for {{ job.brief }}. The "
    "lessons are in your schedule.{% if job.notes %}\n\nNotes: {{ job.notes }}{% endif %}" + SIGN,
)
DEFAULTS[("job_intro_tutor", "in_app")] = ("New job: {{ job.name }}", "{{ job.brief }}")
DEFAULTS[("job_intro_client", "email")] = (
    "Meet your tutor, {{ job.tutor }}",
    "Hello {{ recipient.first_name }},\n\n{{ job.tutor }} will be teaching {{ job.name }}."
    "{% if job.headline %}\n\n{{ job.headline }}{% endif %}" + SIGN,
)
DEFAULTS[("job_posting", "email")] = (
    "New job: {{ posting.title }}",
    "Hello {{ recipient.first_name }},\n\nA new job is open: {{ posting.brief }}. Apply in "
    "the tutor portal: {{ posting.link }}" + SIGN,
)
DEFAULTS[("job_posting", "in_app")] = ("New job: {{ posting.title }}", "{{ posting.brief }}")
DEFAULTS[("job_application_unsuccessful", "email")] = (
    "{{ posting.title }}",
    "Hello {{ recipient.first_name }},\n\nThank you for applying for {{ posting.title }}. "
    "Another tutor has been chosen this time." + SIGN,
)
DEFAULTS[("job_application_unsuccessful", "in_app")] = (
    "{{ posting.title }}",
    "Another tutor was chosen this time.",
)
DEFAULTS[("cover_request", "email")] = (
    "Cover needed: {{ cover.title }}",
    "Hello {{ recipient.first_name }},\n\nCan you cover {{ cover.lessons }} lesson(s), "
    'starting {{ cover.first|datetime("short") }}? Accept in the tutor portal: '
    "{{ cover.link }}" + SIGN,
)
DEFAULTS[("cover_request", "sms")] = (
    "",
    "{{ organisation.name }}: cover needed for {{ cover.title }}. Accept here: {{ cover.link }}",
)
DEFAULTS[("cover_request", "in_app")] = ("Cover needed", "{{ cover.title }}")


for _channel in ("email", "sms", "in_app"):
    DEFAULTS[("automation_message", _channel)] = ("{{ message.subject }}", "{{ message.body }}")


def default_template(type_key: str, channel: str) -> tuple[str, str] | None:
    return DEFAULTS.get((type_key, channel))

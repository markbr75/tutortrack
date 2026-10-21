"""Permission codenames owned by recruitment and compliance (E18 §6)."""

PERMISSIONS = {
    "recruitment.application.view": "See job applications",
    "recruitment.application.edit": "Work applications: move, score, interview, references",
    "recruitment.application.decide": "Approve or reject applications",
    "recruitment.pipeline.manage": "Manage job openings, stages and onboarding checklists",
    "compliance.view": "See tutors' compliance records and documents",
    "compliance.verify": "Verify or reject compliance records",
    "compliance.manage_types": "Configure compliance requirements",
    "compliance.override_restriction": "Assign restricted tutors (with a reason)",
    "compliance.checks.request": "Start and cancel online background checks",
    "compliance.checks.results": "Read background check results and certificates (audited)",
    # Gap batch G5a (FR-18-9).
    "recruitment.performance.view": "See tutors' probation reviews and performance notes",
    "recruitment.performance.manage": "Record probation reviews and performance notes",
    "recruitment.offboarding.manage": "Offboard tutors: checklist, access and final pay",
}

from django.apps import AppConfig


class RecruitmentConfig(AppConfig):
    name = "tutortrack.recruitment"
    label = "recruitment"
    verbose_name = "Recruitment and compliance"

    def ready(self) -> None:
        from tutortrack.crm import targets
        from tutortrack.payroll.services import register_hold_rule

        from . import handlers, org_settings  # noqa: F401
        from .compliance import compliance_hold
        from .models import TutorApplication

        targets.register(
            "recruitment.application",
            TutorApplication,
            "recruitment.application.view",
            "Application",
        )
        register_hold_rule("compliance", compliance_hold)

        from tutortrack.core.permissions import has_perm
        from tutortrack.core.storage.services import register_access_rule

        register_access_rule(
            "recruitment.compliancerecord", lambda user, stored: has_perm(user, "compliance.view")
        )
        register_access_rule(
            "recruitment.tutorapplication",
            lambda user, stored: has_perm(user, "recruitment.application.view"),
        )

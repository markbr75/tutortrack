from django.apps import AppConfig


class LeadsConfig(AppConfig):
    name = "tutortrack.leads"
    label = "leads"
    verbose_name = "Leads and enquiries"

    def ready(self) -> None:
        from tutortrack.crm import targets

        from . import handlers, notifications, org_settings  # noqa: F401
        from .models import Enquiry

        targets.register("leads.enquiry", Enquiry, "leads.enquiry.view", "Enquiry")

        # G5a: files uploaded on public forms (``core.storage.public``).
        from tutortrack.core.permissions import has_perm
        from tutortrack.core.storage import public
        from tutortrack.core.storage.services import register_access_rule

        from .forms import upload_kinds_for_form

        public.register_context("form", upload_kinds_for_form)
        for label in ("leads.enquiry", "leads.formsubmission"):
            register_access_rule(label, lambda user, stored: has_perm(user, "leads.enquiry.view"))

from django.apps import AppConfig


class LeadsConfig(AppConfig):
    name = "tutortrack.leads"
    label = "leads"
    verbose_name = "Leads and enquiries"

    def ready(self) -> None:
        from tutortrack.crm import targets

        from . import handlers, org_settings  # noqa: F401
        from .models import Enquiry

        targets.register("leads.enquiry", Enquiry, "leads.enquiry.view", "Enquiry")

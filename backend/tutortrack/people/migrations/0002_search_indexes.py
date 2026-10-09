"""Global search (FR-05-11, E05-T08): trigram indexes for fuzzy name/email/phone lookup."""

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


def trgm(name, fields):
    return GinIndex(fields=fields, name=name, opclasses=["gin_trgm_ops"] * len(fields))


class Migration(migrations.Migration):
    dependencies = [("people", "0001_initial")]

    operations = [
        TrigramExtension(),
        migrations.AddIndex("client", trgm("client_name_trgm", ["display_name"])),
        migrations.AddIndex("contact", trgm("contact_name_trgm", ["first_name", "last_name"])),
        migrations.AddIndex("contact", trgm("contact_email_trgm", ["email"])),
        migrations.AddIndex("contact", trgm("contact_phone_trgm", ["phone", "mobile"])),
        migrations.AddIndex("student", trgm("student_name_trgm", ["first_name", "last_name"])),
        migrations.AddIndex("tutorprofile", trgm("tutor_name_trgm", ["first_name", "last_name"])),
        migrations.AddIndex("tutorprofile", trgm("tutor_email_trgm", ["email"])),
    ]

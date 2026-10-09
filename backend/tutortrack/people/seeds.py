"""Demo families, students and tutors for the brightminds organisation (E05)."""

from tutortrack.core.context import tenant_context
from tutortrack.core.seeding import SeedContext, seed_step

FAMILIES = [
    (
        {"first_name": "Priya", "last_name": "Patel", "email": "priya.patel@example.com"},
        [
            {
                "first_name": "Arjun",
                "year_group": "Year 10",
                "subjects": [{"subject": "Maths", "level": "GCSE"}],
            },
            {"first_name": "Maya", "year_group": "Year 7", "subjects": [{"subject": "English"}]},
        ],
    ),
    (
        {"first_name": "Tom", "last_name": "Okafor", "email": "tom.okafor@example.com"},
        [
            {
                "first_name": "Ada",
                "year_group": "Year 12",
                "subjects": [{"subject": "Physics", "level": "A level"}],
            }
        ],
    ),
    (
        {
            "first_name": "Grace",
            "last_name": "Hughes",
            "email": "grace.hughes@example.com",
            "relationship": "self",
        },
        [],
    ),
]

TUTORS = [
    ("nia.adeyemi@example.com", "Nia", "Adeyemi", [{"subject": "Maths", "level": "GCSE"}]),
    ("sam.clarke@example.com", "Sam", "Clarke", [{"subject": "Physics", "level": "A level"}]),
]


@seed_step(order=50)
def families_and_tutors(ctx: SeedContext) -> None:
    from tutortrack.people import services
    from tutortrack.people.models import Client, TutorProfile

    with tenant_context(ctx.organisation):
        if not Client.objects.exists():
            for contact, students in FAMILIES:
                client, _contact, _students = services.quick_add_family(
                    contact=contact, students=students
                )
                ctx.log(f"    created {client.display_name}")
        for email, first, last, subjects in TUTORS:
            if TutorProfile.objects.filter(email=email).exists():
                continue
            tutor = services.create_tutor(
                email=email, first_name=first, last_name=last, invite=False
            )
            services.set_tutor_subjects(tutor, subjects)
            ctx.log(f"    created tutor {tutor.full_name}")

"""Public website data in erasure (E24 data, E29 Part 2): an erased tutor's public profile
is taken down and its photos released; testimonials lose the person's name."""

from __future__ import annotations

from django.db.models import Q

from tutortrack.privacy.registry import ErasureContext, ErasureOutcome, Person, Provider, register

from .models import PublicProfile, Testimonial


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    for profile in PublicProfile.objects.filter(tutor_id__in=person.of("people.tutor")):
        out.file_ids += [str(f) for f in (profile.photo_id, profile.draft_photo_id) if f]
        PublicProfile.objects.filter(pk=profile.pk).update(
            status=PublicProfile.Status.HIDDEN,
            listed=False,
            published={},
            draft={},
            photo=None,
            draft_photo=None,
        )
        out.anonymised += 1
    tutors = person.of("people.tutor")
    for testimonial in Testimonial.objects.filter(
        Q(tutor_id__in=tutors) | Q(author__in=sorted(person.names))
    ):
        quote, author = ctx.scrub(testimonial.quote), ctx.scrub(testimonial.author)
        if (quote, author) != (testimonial.quote, testimonial.author):
            Testimonial.objects.filter(pk=testimonial.pk).update(
                quote=quote, author=author, published=False
            )
            out.anonymised += 1
    return out


register(Provider(key="sites", label="Website", erase=erase, order=39))

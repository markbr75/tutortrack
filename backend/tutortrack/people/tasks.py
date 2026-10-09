from __future__ import annotations

from celery import shared_task

from tutortrack.core.tasks import TenantTask


@shared_task(base=TenantTask, name="tutortrack.people.tasks.geocode_address", ignore_result=True)
def geocode_address(*, address_id: str, organisation_id: str) -> None:
    from tutortrack.core.geo import geocoder
    from tutortrack.core.time import now

    from .models import Address

    address = Address.objects.filter(pk=address_id).first()
    if address is None or not address.one_line():
        return
    point = geocoder().geocode(address.one_line(), address.country)
    if point is None:
        return
    Address.objects.filter(pk=address.pk).update(lat=point.lat, lng=point.lng, geocoded_at=now())

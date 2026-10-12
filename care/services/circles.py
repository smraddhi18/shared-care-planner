from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from rest_framework.exceptions import ValidationError

from ..models import CareCircle, Membership
from .audit import audit


def create_circle(user, name, recipient_display_name, zone_name):
    try:
        ZoneInfo(zone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValidationError({"timezone": "Unknown IANA time zone"}) from exc
    with transaction.atomic():
        circle = CareCircle.objects.create(
            name=name, recipient_display_name=recipient_display_name, timezone=zone_name, created_by=user
        )
        Membership.objects.create(circle=circle, user=user, role=Membership.Role.ORGANIZER)
        audit(circle, user, "circle.created", circle)
        return circle

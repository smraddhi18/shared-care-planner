from django.db import transaction

from ..models import Membership, Notification
from .access import membership_for
from .audit import audit


def create_appointment(user, circle, values):
    membership_for(user, circle, [Membership.Role.ORGANIZER, Membership.Role.CAREGIVER])
    with transaction.atomic():
        appointment = circle.appointments.create(created_by=user, **values)
        audit(circle, user, "appointment.created", appointment)
    return appointment


def update_appointment(user, appointment, changes):
    membership_for(user, appointment.circle, [Membership.Role.ORGANIZER, Membership.Role.CAREGIVER])
    with transaction.atomic():
        for field, value in changes.items():
            setattr(appointment, field, value)
        appointment.save()
        Notification.objects.filter(
            appointment=appointment, status__in=[Notification.Status.PENDING, Notification.Status.PROCESSING]
        ).delete()
        audit(appointment.circle, user, "appointment.updated", appointment, {"fields": sorted(changes)})
    return appointment

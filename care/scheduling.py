from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from .models import Appointment, Membership, Notification, Occurrence, TaskTemplate


def resolve_local(local_date, local_time, zone_name):
    """Use first fold for repeated times; advance to first valid minute for gaps."""
    zone = ZoneInfo(zone_name)
    wall = datetime.combine(local_date, local_time).replace(second=0, microsecond=0)
    for _ in range(180):
        candidate = wall.replace(tzinfo=zone, fold=0)
        roundtrip = candidate.astimezone(UTC).astimezone(zone)
        if roundtrip.replace(tzinfo=None) == wall:
            return candidate.astimezone(UTC)
        wall += timedelta(minutes=1)
    raise ValueError("No valid local time within three hours")


def generate_occurrences(now=None, horizon_days=7):
    now = now or timezone.now()
    created = 0
    for template in TaskTemplate.objects.filter(active=True).select_related("circle"):
        today = now.astimezone(ZoneInfo(template.circle.timezone)).date()
        for offset in range(-1, horizon_days + 1):
            day = today + timedelta(days=offset)
            if day < template.start_date:
                continue
            if template.frequency == TaskTemplate.Frequency.WEEKLY and day.weekday() not in template.weekdays:
                continue
            scheduled_for = resolve_local(day, template.local_time, template.circle.timezone)
            _, new = Occurrence.objects.get_or_create(
                template=template, local_date=day, defaults={"scheduled_for": scheduled_for}
            )
            created += int(new)
    return created


def _active_recipients(circle, assigned_to_id):
    members = Membership.objects.filter(circle=circle, active=True)
    if (
        assigned_to_id
        and members.filter(user_id=assigned_to_id).exclude(role=Membership.Role.VIEWER).exists()
    ):
        return [assigned_to_id]
    return list(members.filter(role=Membership.Role.ORGANIZER).values_list("user_id", flat=True))


def _queue(circle, recipient_id, kind, *, occurrence=None, appointment=None):
    source = f"o{occurrence.pk}" if occurrence else f"a{appointment.pk}"
    if occurrence and kind == Notification.Kind.DUE and occurrence.snoozed_until:
        source += f"-s{int(occurrence.snoozed_until.timestamp())}"
    for channel in (Notification.Channel.EMAIL, Notification.Channel.IN_APP):
        Notification.objects.get_or_create(
            key=f"{source}:{kind}:{recipient_id}:{channel}",
            defaults={
                "circle": circle,
                "recipient_id": recipient_id,
                "occurrence": occurrence,
                "appointment": appointment,
                "kind": kind,
                "channel": channel,
            },
        )


def enqueue_due(now=None):
    now = now or timezone.now()
    count = 0
    due = Occurrence.objects.filter(
        template__active=True, state=Occurrence.State.PENDING, scheduled_for__lte=now
    ).select_related("template__circle")
    for occurrence in due.iterator():
        due_at = occurrence.snoozed_until or occurrence.scheduled_for
        if due_at > now:
            continue
        for user_id in _active_recipients(occurrence.template.circle, occurrence.template.assigned_to_id):
            _queue(occurrence.template.circle, user_id, Notification.Kind.DUE, occurrence=occurrence)
            count += 1
    return count


def enqueue_escalations(now=None):
    now = now or timezone.now()
    count = 0
    pending = Occurrence.objects.filter(
        template__active=True, state=Occurrence.State.PENDING, scheduled_for__lte=now - timedelta(minutes=15)
    ).select_related("template__circle")
    for occurrence in pending.iterator():
        if (occurrence.snoozed_until or occurrence.scheduled_for) + timedelta(
            minutes=occurrence.template.grace_minutes
        ) > now:
            continue
        for user_id in Membership.objects.filter(
            circle=occurrence.template.circle, active=True, role=Membership.Role.ORGANIZER
        ).values_list("user_id", flat=True):
            _queue(occurrence.template.circle, user_id, Notification.Kind.ESCALATION, occurrence=occurrence)
            count += 1
    return count


def enqueue_appointments(now=None):
    now = now or timezone.now()
    count = 0
    for appointment in Appointment.objects.filter(
        starts_at__gte=now - timedelta(hours=24), starts_at__lte=now + timedelta(days=1)
    ).select_related("circle"):
        if appointment.starts_at - timedelta(minutes=appointment.reminder_minutes) > now:
            continue
        for user_id in _active_recipients(appointment.circle, appointment.assigned_to_id):
            _queue(appointment.circle, user_id, Notification.Kind.APPOINTMENT, appointment=appointment)
            count += 1
    return count


def scheduler_tick():
    with transaction.atomic():
        generated = generate_occurrences()
        due = enqueue_due()
        escalations = enqueue_escalations()
        appointments = enqueue_appointments()
    return {"generated": generated, "due": due, "escalations": escalations, "appointments": appointments}

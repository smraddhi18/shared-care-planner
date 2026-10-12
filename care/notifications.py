import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Membership, Notification, Occurrence

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
LEASE_SECONDS = 120


def claim_one(now=None):
    now = now or timezone.now()
    with transaction.atomic():
        item = (
            Notification.objects.select_for_update(skip_locked=True)
            .filter(
                Q(status=Notification.Status.PENDING, next_attempt_at__lte=now)
                | Q(status=Notification.Status.PROCESSING, lease_until__lte=now)
            )
            .order_by("next_attempt_at", "pk")
            .first()
        )
        if item is None:
            return None
        item.status = Notification.Status.PROCESSING
        item.lease_token = uuid.uuid4()
        item.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        item.attempts += 1
        item.save(update_fields=["status", "lease_token", "lease_until", "attempts"])
        return item.pk, item.lease_token


def _valid(item):
    if not Membership.objects.filter(circle=item.circle, user=item.recipient, active=True).exists():
        return False
    if item.occurrence_id:
        occurrence = Occurrence.objects.select_for_update().get(pk=item.occurrence_id)
        if not occurrence.template.active:
            return False
        if item.kind == Notification.Kind.ESCALATION and occurrence.state != Occurrence.State.PENDING:
            return False
        if item.kind == Notification.Kind.DUE and (
            occurrence.state != Occurrence.State.PENDING
            or (occurrence.snoozed_until and occurrence.snoozed_until > timezone.now())
        ):
            return False
    return True


def _message(item):
    link = f"{settings.PUBLIC_BASE_URL}/circle/{item.circle_id}/"
    if item.kind == Notification.Kind.ESCALATION:
        return (
            "Care task unacknowledged",
            f"A care task has not been acknowledged. Sign in to review it: {link}",
        )
    if item.kind == Notification.Kind.APPOINTMENT:
        return "Appointment reminder", f"An appointment is coming up. Sign in for details: {link}"
    return "Care task reminder", f"A care task is due. Sign in for details: {link}"


def deliver_one(now=None):
    claimed = claim_one(now)
    if claimed is None:
        return False
    pk, lease_token = claimed
    try:
        with transaction.atomic():
            item = Notification.objects.select_related("recipient", "circle", "occurrence").get(pk=pk)
            if not _valid(item):
                Notification.objects.filter(pk=pk, lease_token=lease_token).update(
                    status=Notification.Status.CANCELED, lease_token=None, lease_until=None
                )
                return True
            if item.channel == Notification.Channel.EMAIL:
                subject, body = _message(item)
                send_mail(
                    subject, body, settings.DEFAULT_FROM_EMAIL, [item.recipient.email], fail_silently=False
                )
            Notification.objects.filter(pk=pk, lease_token=lease_token).update(
                status=Notification.Status.SENT,
                sent_at=timezone.now(),
                lease_token=None,
                lease_until=None,
                last_error="",
            )
    except Exception as exc:
        logger.exception("notification_delivery_failed", extra={"notification_id": pk})
        if item.attempts >= MAX_ATTEMPTS:
            Notification.objects.filter(pk=pk, lease_token=lease_token).update(
                status=Notification.Status.DEAD,
                lease_token=None,
                lease_until=None,
                last_error=type(exc).__name__[:240],
            )
        else:
            delay = min(3600, 30 * (2 ** (item.attempts - 1)))
            Notification.objects.filter(pk=pk, lease_token=lease_token).update(
                status=Notification.Status.PENDING,
                lease_token=None,
                lease_until=None,
                next_attempt_at=timezone.now() + timedelta(seconds=delay),
                last_error=type(exc).__name__[:240],
            )
    return True


def deliver_batch(limit=100):
    processed = 0
    while processed < limit and deliver_one():
        processed += 1
    return processed

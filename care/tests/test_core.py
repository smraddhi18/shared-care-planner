import time as time_module
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.db import connection, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from care.models import Membership, Notification, Occurrence, TaskTemplate
from care.notifications import deliver_batch, deliver_one
from care.scheduling import (
    enqueue_escalations,
    generate_occurrences,
    resolve_local,
    scheduler_tick,
)
from care.services.circles import create_circle
from care.services.invitations import accept_invitation, create_invite
from care.services.occurrences import update_occurrence


def make_task(owner, helper, circle, *, when=None, category="care"):
    local = (when or timezone.now()).astimezone(ZoneInfo(circle.timezone))
    return TaskTemplate.objects.create(
        circle=circle,
        title="Check in",
        category=category,
        frequency="daily",
        local_time=local.time().replace(second=0, microsecond=0),
        start_date=local.date(),
        assigned_to=helper,
        created_by=owner,
    )


def test_dst_gap_moves_forward_and_fold_uses_earlier_instant():
    gap = resolve_local(date(2026, 3, 8), time(2, 30), "America/New_York")
    assert gap.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M") == "03:00"
    fold = resolve_local(date(2026, 11, 1), time(1, 30), "America/New_York")
    assert fold == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)


@pytest.mark.django_db
def test_occurrence_generation_is_idempotent(people):
    owner, helper, _, circle = people
    task = make_task(owner, helper, circle)
    generate_occurrences(horizon_days=1)
    generate_occurrences(horizon_days=1)
    assert Occurrence.objects.filter(template=task).count() == 2


@pytest.mark.django_db
def test_circle_isolation_and_roles(people):
    owner, helper, outsider, circle = people
    client = APIClient()
    client.force_authenticate(user=outsider)
    assert client.get(f"/api/v1/circles/{circle.pk}/").status_code == 404
    client.force_authenticate(user=helper)
    response = client.post(
        f"/api/v1/circles/{circle.pk}/tasks/",
        {
            "title": "Medication",
            "category": "medication",
            "frequency": "daily",
            "local_time": "09:00",
            "start_date": "2026-09-28",
        },
        format="json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_invite_is_one_use_and_email_bound(people):
    owner, helper, outsider, circle = people
    invite, token = create_invite(owner, circle, "outside@example.test", "viewer")
    with pytest.raises(PermissionDenied):
        accept_invitation(helper, token)
    assert accept_invitation(outsider, token) == circle
    with pytest.raises(ValidationError):
        accept_invitation(outsider, token)


@pytest.mark.django_db
def test_expired_invite_is_rejected(people):
    owner, _, outsider, circle = people
    invite, token = create_invite(owner, circle, outsider.email, "viewer")
    invite.expires_at = timezone.now() - timedelta(seconds=1)
    invite.save(update_fields=["expires_at"])
    with pytest.raises(ValidationError):
        accept_invitation(outsider, token)
    assert not Membership.objects.filter(circle=circle, user=outsider).exists()


@pytest.mark.django_db
def test_due_email_is_generic_and_worker_recovers_expired_lease(people):
    owner, helper, _, circle = people
    task = make_task(owner, helper, circle, when=timezone.now() - timedelta(minutes=2), category="medication")
    scheduler_tick()
    item = Notification.objects.get(occurrence__template=task, kind="due", channel="email")
    item.status = "processing"
    item.lease_until = timezone.now() - timedelta(seconds=1)
    item.save(update_fields=["status", "lease_until"])
    with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
        deliver_batch()
    item.refresh_from_db()
    assert item.status == "sent"
    assert len(mail.outbox) >= 1
    assert "Medication" not in mail.outbox[0].subject
    assert "Check in" not in mail.outbox[0].body


@pytest.mark.django_db
def test_email_failure_retries_without_losing_notification(people):
    owner, helper, _, circle = people
    make_task(owner, helper, circle, when=timezone.now() - timedelta(minutes=2))
    scheduler_tick()
    with patch("care.notifications.send_mail", side_effect=RuntimeError("smtp down")):
        assert deliver_one()
    item = Notification.objects.filter(kind="due", channel="email").first()
    assert item is not None
    assert item.status == "pending"
    assert item.attempts == 1
    assert item.next_attempt_at > timezone.now()


@pytest.mark.django_db
def test_acknowledged_task_does_not_escalate(people):
    owner, helper, _, circle = people
    task = make_task(owner, helper, circle, when=timezone.now() - timedelta(minutes=45))
    generate_occurrences(horizon_days=0)
    occurrence = Occurrence.objects.get(
        template=task, local_date=timezone.now().astimezone(ZoneInfo(circle.timezone)).date()
    )
    update_occurrence(helper, occurrence, "acknowledge")
    enqueue_escalations()
    assert not Notification.objects.filter(occurrence=occurrence, kind="escalation").exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("first_action", "repeat_action", "rejected_action", "expected_state"),
    [
        ("complete", "complete", "skip", Occurrence.State.COMPLETED),
        ("skip", "skip", "complete", Occurrence.State.SKIPPED),
    ],
)
def test_occurrence_action_transitions_are_idempotent_and_reject_conflicts(
    people, first_action, repeat_action, rejected_action, expected_state
):
    owner, helper, _, circle = people
    task = make_task(owner, helper, circle)
    generate_occurrences(horizon_days=0)
    occurrence = Occurrence.objects.get(
        template=task, local_date=timezone.now().astimezone(ZoneInfo(circle.timezone)).date()
    )
    update_occurrence(helper, occurrence, first_action)
    update_occurrence(helper, occurrence, repeat_action)
    occurrence.refresh_from_db()
    assert occurrence.state == expected_state
    assert occurrence.acknowledged_at is not None
    with pytest.raises(ValidationError):
        update_occurrence(helper, occurrence, rejected_action)


@pytest.mark.django_db
def test_unknown_occurrence_action_is_rejected(people):
    owner, helper, _, circle = people
    task = make_task(owner, helper, circle)
    generate_occurrences(horizon_days=0)
    occurrence = Occurrence.objects.get(
        template=task, local_date=timezone.now().astimezone(ZoneInfo(circle.timezone)).date()
    )
    with pytest.raises(ValidationError):
        update_occurrence(helper, occurrence, "unsupported")


@pytest.mark.django_db(transaction=True)
def test_concurrent_acknowledgement_cancels_queued_escalation():
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    User = get_user_model()
    owner = User.objects.create_user("owner@race.test", "owner@race.test", "A-secure-password-123")
    helper = User.objects.create_user("helper@race.test", "helper@race.test", "A-secure-password-123")
    circle = create_circle(owner, "Race test", "Alex", "UTC")
    Membership.objects.create(circle=circle, user=helper, role=Membership.Role.CAREGIVER)
    task = make_task(owner, helper, circle, when=timezone.now() - timedelta(minutes=45))
    generate_occurrences(horizon_days=0)
    enqueue_escalations()
    occurrence = Occurrence.objects.get(template=task, local_date=timezone.now().date())
    item = Notification.objects.get(occurrence=occurrence, kind="escalation", channel="email")
    Notification.objects.exclude(pk=item.pk).update(status=Notification.Status.CANCELED)

    def deliver_in_thread():
        try:
            return deliver_one()
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            Occurrence.objects.select_for_update().get(pk=occurrence.pk)
            future = pool.submit(deliver_in_thread)
            deadline = time_module.monotonic() + 5
            while time_module.monotonic() < deadline:
                item.refresh_from_db()
                if item.status == Notification.Status.PROCESSING:
                    break
                time_module.sleep(0.02)
            assert item.status == Notification.Status.PROCESSING
            update_occurrence(helper, occurrence, "acknowledge")
        # The worker resumes after the acknowledgement transaction commits.
        assert future.result(timeout=5)
    item.refresh_from_db()
    assert item.status == Notification.Status.CANCELED


@pytest.mark.django_db
def test_unacknowledged_task_escalates_to_organizer(people):
    owner, helper, _, circle = people
    task = make_task(owner, helper, circle, when=timezone.now() - timedelta(minutes=45))
    generate_occurrences(horizon_days=0)
    enqueue_escalations()
    assert (
        Notification.objects.filter(occurrence__template=task, recipient=owner, kind="escalation").count()
        == 2
    )


@pytest.mark.django_db
def test_revocation_blocks_access(people):
    owner, helper, _, circle = people
    member = Membership.objects.get(circle=circle, user=helper)
    member.active = False
    member.save(update_fields=["active"])
    client = APIClient()
    client.force_authenticate(user=helper)
    assert client.get(f"/api/v1/circles/{circle.pk}/").status_code == 404

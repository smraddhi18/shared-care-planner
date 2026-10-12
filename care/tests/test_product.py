from datetime import time, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from care.models import AuditEvent, EmailVerification, Membership, Notification, Occurrence, TaskTemplate
from care.notifications import deliver_batch
from care.scheduling import enqueue_appointments, enqueue_due, generate_occurrences, scheduler_tick
from care.services.circles import create_circle
from care.services.occurrences import update_occurrence


@pytest.mark.django_db
def test_signup_verifies_email_before_login():
    client = Client()
    with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
        response = client.post(
            "/signup/",
            {
                "email": "new@example.test",
                "password1": "A-long-test-password-123",
                "password2": "A-long-test-password-123",
            },
        )
    assert response.status_code == 200
    user = get_user_model().objects.get(email="new@example.test")
    assert not user.is_active
    assert EmailVerification.objects.filter(user=user, used_at__isnull=True).exists()
    assert "/verify/" in mail.outbox[-1].body
    assert (
        client.post(
            "/login/", {"username": user.username, "password": "A-long-test-password-123"}
        ).status_code
        == 200
    )
    assert "_auth_user_id" not in client.session
    link = mail.outbox[-1].body.split("Open this link to verify your email: ")[-1].strip()
    response = client.get(link.replace("http://localhost:8000", ""))
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.is_active
    assert client.session["_auth_user_id"] == str(user.pk)


@pytest.mark.django_db
def test_resend_verification_and_password_reset():
    User = get_user_model()
    inactive = User.objects.create_user(
        "inactive@example.test", "inactive@example.test", "Original-password-123"
    )
    inactive.is_active = False
    inactive.save(update_fields=["is_active"])
    active = User.objects.create_user("active@example.test", "active@example.test", "Original-password-123")
    client = Client()
    with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
        response = client.post("/resend-verification/", {"email": inactive.email})
        assert response.status_code == 200
        assert EmailVerification.objects.filter(user=inactive, used_at__isnull=True).exists()
        assert len(mail.outbox) == 1
        response = client.post("/password-reset/", {"email": active.email})
        assert response.status_code == 302
        reset_url = next(line for line in mail.outbox[-1].body.splitlines() if "/password-reset/" in line)
        response = client.get(urlparse(reset_url).path)
        assert response.status_code == 302
        response = client.post(
            response.headers["Location"],
            {"new_password1": "Updated-password-123", "new_password2": "Updated-password-123"},
        )
        assert response.status_code == 302
    active.refresh_from_db()
    assert active.check_password("Updated-password-123")


@pytest.mark.django_db
def test_ui_and_api_enforce_circle_membership():
    User = get_user_model()
    owner = User.objects.create_user("owner@example.test", "owner@example.test", "A-password-123")
    outsider = User.objects.create_user("outsider@example.test", "outsider@example.test", "A-password-123")
    circle = create_circle(owner, "Home", "Sam", "Asia/Kolkata")
    client = Client()
    client.force_login(outsider)
    assert client.get(f"/circle/{circle.pk}/").status_code == 404
    assert client.get(f"/api/v1/circles/{circle.pk}/tasks/").status_code == 404


@pytest.mark.django_db
def test_api_creates_circle_with_validated_timezone():
    user = get_user_model().objects.create_user(
        "new-organizer@example.test", "new-organizer@example.test", "A-password-123"
    )
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post(
        "/api/v1/circles/",
        {"name": "Home", "recipient_display_name": "Sam", "timezone": "UTC"},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert Membership.objects.filter(circle_id=response.data["id"], user=user, role="organizer").exists()


@pytest.mark.django_db
def test_api_task_to_acknowledgement_and_notification(people):
    owner, helper, _, circle = people
    client = APIClient()
    client.force_authenticate(user=owner)
    local = (timezone.now() - timedelta(minutes=1)).astimezone(ZoneInfo(circle.timezone))
    response = client.post(
        f"/api/v1/circles/{circle.pk}/tasks/",
        {
            "title": "Water break",
            "category": "care",
            "frequency": "daily",
            "local_time": local.strftime("%H:%M"),
            "start_date": str(local.date()),
            "assigned_to": helper.pk,
            "grace_minutes": 30,
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    task = TaskTemplate.objects.get(pk=response.data["id"])
    occurrence = Occurrence.objects.get(template=task, local_date=local.date())
    scheduler_tick()
    assert Notification.objects.filter(occurrence=occurrence, kind="due").count() == 2
    client.force_authenticate(user=helper)
    response = client.post(
        f"/api/v1/occurrences/{occurrence.pk}/actions/", {"action": "acknowledge"}, format="json"
    )
    assert response.status_code == 200
    occurrence.refresh_from_db()
    assert occurrence.state == "acknowledged"
    assert AuditEvent.objects.filter(circle=circle, action="occurrence.acknowledge").exists()


@pytest.mark.django_db
def test_task_schedule_update_replaces_future_occurrences(people):
    owner, helper, _, circle = people
    local_date = timezone.now().astimezone(ZoneInfo(circle.timezone)).date() + timedelta(days=1)
    task = TaskTemplate.objects.create(
        circle=circle,
        title="Morning check",
        frequency="daily",
        local_time=time(9),
        start_date=local_date,
        assigned_to=helper,
        created_by=owner,
    )
    generate_occurrences(horizon_days=2)
    old_occurrence = Occurrence.objects.get(template=task, local_date=local_date)
    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.patch(
        f"/api/v1/circles/{circle.pk}/tasks/{task.pk}/", {"local_time": "10:00"}, format="json"
    )
    assert response.status_code == 200, response.data
    new_occurrence = Occurrence.objects.get(template=task, local_date=local_date)
    assert new_occurrence.pk != old_occurrence.pk
    assert new_occurrence.scheduled_for.astimezone(ZoneInfo(circle.timezone)).hour == 10
    assert AuditEvent.objects.filter(circle=circle, action="task.updated").exists()


@pytest.mark.django_db
def test_appointment_update_cancels_pending_alerts(people):
    owner, helper, _, circle = people
    client = APIClient()
    client.force_authenticate(user=owner)
    start = timezone.now() + timedelta(minutes=30)
    response = client.post(
        f"/api/v1/circles/{circle.pk}/appointments/",
        {
            "title": "Transport",
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=1)).isoformat(),
            "assigned_to": helper.pk,
            "reminder_minutes": 60,
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    appointment_id = response.data["id"]
    enqueue_appointments()
    assert Notification.objects.filter(appointment_id=appointment_id, status="pending").count() == 2
    response = client.patch(
        f"/api/v1/circles/{circle.pk}/appointments/{appointment_id}/",
        {
            "starts_at": (start + timedelta(hours=2)).isoformat(),
            "ends_at": (start + timedelta(hours=3)).isoformat(),
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    assert not Notification.objects.filter(appointment_id=appointment_id, status="pending").exists()
    assert AuditEvent.objects.filter(circle=circle, action="appointment.updated").exists()


@pytest.mark.django_db
def test_member_revocation_protects_last_organizer(people):
    owner, helper, _, circle = people
    owner_member = Membership.objects.get(circle=circle, user=owner)
    helper_member = Membership.objects.get(circle=circle, user=helper)
    client = APIClient()
    client.force_authenticate(user=owner)
    assert client.post(f"/api/v1/circles/{circle.pk}/members/{owner_member.pk}/revoke/").status_code == 400
    assert client.post(f"/api/v1/circles/{circle.pk}/members/{helper_member.pk}/revoke/").status_code == 200
    client.force_authenticate(user=helper)
    assert client.get(f"/api/v1/circles/{circle.pk}/").status_code == 404


@pytest.mark.django_db
def test_snooze_delays_and_requeues_reminder(people):
    owner, helper, _, circle = people
    local = (timezone.now() - timedelta(minutes=2)).astimezone(ZoneInfo(circle.timezone))
    task = TaskTemplate.objects.create(
        circle=circle,
        title="Check",
        frequency="daily",
        local_time=local.time().replace(second=0, microsecond=0),
        start_date=local.date(),
        assigned_to=helper,
        created_by=owner,
    )
    generate_occurrences(horizon_days=0)
    occurrence = Occurrence.objects.get(template=task, local_date=local.date())
    enqueue_due()
    assert Notification.objects.filter(occurrence=occurrence, kind="due").count() == 2
    snoozed_until = timezone.now() + timedelta(minutes=15)
    update_occurrence(helper, occurrence, "snooze", snoozed_until)
    enqueue_due()
    assert Notification.objects.filter(occurrence=occurrence, kind="due").count() == 2
    with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
        deliver_batch()
    assert Notification.objects.filter(occurrence=occurrence, status="canceled").count() == 2
    occurrence.refresh_from_db()
    occurrence.snoozed_until = timezone.now() - timedelta(seconds=1)
    occurrence.save(update_fields=["snoozed_until"])
    enqueue_due()
    assert Notification.objects.filter(occurrence=occurrence, kind="due").count() == 4


@pytest.mark.django_db
def test_revoke_blocks_due_notifications(people):
    owner, helper, _, circle = people
    local = (timezone.now() - timedelta(minutes=2)).astimezone(ZoneInfo(circle.timezone))
    task = TaskTemplate.objects.create(
        circle=circle,
        title="Private",
        frequency="daily",
        local_time=local.time().replace(second=0, microsecond=0),
        start_date=local.date(),
        assigned_to=helper,
        created_by=owner,
    )
    scheduler_tick()
    member = Membership.objects.get(circle=circle, user=helper)
    member.active = False
    member.save(update_fields=["active"])
    with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
        deliver_batch()
    assert (
        Notification.objects.filter(occurrence__template=task, recipient=helper, status="canceled").count()
        == 2
    )

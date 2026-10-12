from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone as dj_timezone


class CareCircle(models.Model):
    name = models.CharField(max_length=120)
    recipient_display_name = models.CharField(max_length=120)
    timezone = models.CharField(max_length=64, default="Asia/Kolkata")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=dj_timezone.now)

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        ORGANIZER = "organizer", "Organizer"
        CAREGIVER = "caregiver", "Caregiver"
        VIEWER = "viewer", "Viewer"

    circle = models.ForeignKey(CareCircle, related_name="memberships", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=12, choices=Role.choices)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=dj_timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["circle", "user"], name="one_membership_per_user_circle")
        ]
        indexes = [models.Index(fields=["user", "active"])]


class EmailVerification(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)


class Invitation(models.Model):
    circle = models.ForeignKey(CareCircle, on_delete=models.CASCADE)
    email = models.EmailField()
    role = models.CharField(max_length=12, choices=Membership.Role.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=dj_timezone.now)

    class Meta:
        indexes = [models.Index(fields=["circle", "email"])]


class TaskTemplate(models.Model):
    class Category(models.TextChoices):
        CARE = "care", "Care task"
        MEDICATION = "medication", "Medication reminder"

    class Frequency(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"

    circle = models.ForeignKey(CareCircle, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=160)
    category = models.CharField(max_length=12, choices=Category.choices, default=Category.CARE)
    frequency = models.CharField(max_length=8, choices=Frequency.choices)
    weekdays = models.JSONField(default=list, blank=True)
    local_time = models.TimeField()
    start_date = models.DateField()
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    grace_minutes = models.PositiveSmallIntegerField(default=30)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="created_tasks", on_delete=models.PROTECT
    )
    created_at = models.DateTimeField(default=dj_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(grace_minutes__gte=15) & Q(grace_minutes__lte=120), name="valid_grace_minutes"
            )
        ]


class Appointment(models.Model):
    circle = models.ForeignKey(CareCircle, on_delete=models.CASCADE, related_name="appointments")
    title = models.CharField(max_length=160)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    reminder_minutes = models.PositiveSmallIntegerField(default=60)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="created_appointments", on_delete=models.PROTECT
    )
    created_at = models.DateTimeField(default=dj_timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=models.F("starts_at")), name="appointment_ends_after_start"
            )
        ]


class Occurrence(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        COMPLETED = "completed", "Completed"
        SKIPPED = "skipped", "Skipped"

    template = models.ForeignKey(TaskTemplate, on_delete=models.CASCADE, related_name="occurrences")
    local_date = models.DateField()
    scheduled_for = models.DateTimeField()
    state = models.CharField(max_length=12, choices=State.choices, default=State.PENDING)
    snoozed_until = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["template", "local_date"], name="unique_template_local_date")
        ]
        indexes = [models.Index(fields=["state", "scheduled_for"])]


class Notification(models.Model):
    class Kind(models.TextChoices):
        DUE = "due", "Task reminder"
        ESCALATION = "escalation", "Unacknowledged task"
        APPOINTMENT = "appointment", "Appointment reminder"

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        IN_APP = "in_app", "In app"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SENT = "sent", "Sent"
        CANCELED = "canceled", "Canceled"
        DEAD = "dead", "Dead"

    key = models.CharField(max_length=180, unique=True)
    circle = models.ForeignKey(CareCircle, on_delete=models.CASCADE)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    occurrence = models.ForeignKey(Occurrence, null=True, blank=True, on_delete=models.CASCADE)
    appointment = models.ForeignKey(Appointment, null=True, blank=True, on_delete=models.CASCADE)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    channel = models.CharField(max_length=8, choices=Channel.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=dj_timezone.now)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(default=dj_timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["status", "next_attempt_at"]),
            models.Index(fields=["recipient", "channel", "read_at"]),
        ]


class AuditEvent(models.Model):
    circle = models.ForeignKey(CareCircle, on_delete=models.CASCADE)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=40)
    target_id = models.CharField(max_length=40)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=dj_timezone.now)

    class Meta:
        indexes = [models.Index(fields=["circle", "created_at"])]

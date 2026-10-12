from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone
from rest_framework import serializers

from .models import Appointment, CareCircle, Membership, Notification, Occurrence, TaskTemplate


class CircleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CareCircle
        fields = ("id", "name", "recipient_display_name", "timezone", "created_at")
        read_only_fields = ("id", "created_at")

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise serializers.ValidationError("Use a valid IANA time zone") from exc
        return value


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskTemplate
        fields = (
            "id",
            "title",
            "category",
            "frequency",
            "weekdays",
            "local_time",
            "start_date",
            "assigned_to",
            "grace_minutes",
            "active",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def validate(self, attrs):
        frequency = attrs.get("frequency", getattr(self.instance, "frequency", None))
        weekdays = attrs.get("weekdays", getattr(self.instance, "weekdays", []))
        if frequency == TaskTemplate.Frequency.WEEKLY and (
            not isinstance(weekdays, list)
            or not weekdays
            or any(type(day) is not int or not 0 <= day <= 6 for day in weekdays)
        ):
            raise serializers.ValidationError({"weekdays": "Choose weekdays numbered 0 to 6"})
        if frequency == TaskTemplate.Frequency.DAILY:
            attrs["weekdays"] = []
        grace = attrs.get("grace_minutes", getattr(self.instance, "grace_minutes", 30))
        if not 15 <= grace <= 120:
            raise serializers.ValidationError({"grace_minutes": "Must be 15 to 120"})
        assigned = attrs.get("assigned_to", getattr(self.instance, "assigned_to", None))
        circle = self.context.get("circle")
        if (
            assigned
            and circle
            and not Membership.objects.filter(circle=circle, user=assigned, active=True)
            .exclude(role=Membership.Role.VIEWER)
            .exists()
        ):
            raise serializers.ValidationError({"assigned_to": "Must be an active caregiver or organizer"})
        return attrs


class AppointmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appointment
        fields = ("id", "title", "starts_at", "ends_at", "assigned_to", "reminder_minutes", "created_at")
        read_only_fields = ("id", "created_at")

    def validate(self, attrs):
        start = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        end = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if start and not self.instance and start < timezone.now() - timedelta(minutes=1):
            raise serializers.ValidationError({"starts_at": "Appointment must be in the future"})
        if start and end and end <= start:
            raise serializers.ValidationError({"ends_at": "Must be after start"})
        if not 0 <= attrs.get("reminder_minutes", getattr(self.instance, "reminder_minutes", 60)) <= 1440:
            raise serializers.ValidationError({"reminder_minutes": "Must be 0 to 1440"})
        assigned = attrs.get("assigned_to", getattr(self.instance, "assigned_to", None))
        circle = self.context.get("circle")
        if (
            assigned
            and circle
            and not Membership.objects.filter(circle=circle, user=assigned, active=True)
            .exclude(role=Membership.Role.VIEWER)
            .exists()
        ):
            raise serializers.ValidationError({"assigned_to": "Must be an active caregiver or organizer"})
        return attrs


class OccurrenceSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source="template.title", read_only=True)
    category = serializers.CharField(source="template.category", read_only=True)

    class Meta:
        model = Occurrence
        fields = (
            "id",
            "title",
            "category",
            "local_date",
            "scheduled_for",
            "state",
            "snoozed_until",
            "acknowledged_at",
            "completed_at",
        )


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ("id", "kind", "channel", "status", "sent_at", "read_at", "created_at")

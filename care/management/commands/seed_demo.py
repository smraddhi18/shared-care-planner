import os
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from care.models import Membership, TaskTemplate
from care.scheduling import scheduler_tick
from care.services.circles import create_circle


class Command(BaseCommand):
    help = "Create synthetic demo users, a family circle, and reminders."

    def handle(self, *args, **options):
        if os.getenv("DEMO_SEED_ALLOWED") != "1":
            raise CommandError("Set DEMO_SEED_ALLOWED=1 explicitly for synthetic demo data")
        password = os.getenv("DEMO_PASSWORD")
        if not password or len(password) < 12:
            raise CommandError("Set DEMO_PASSWORD to at least 12 characters")
        User = get_user_model()
        owner, created = User.objects.get_or_create(
            username="organizer@demo.invalid", defaults={"email": "organizer@demo.invalid", "is_active": True}
        )
        if created:
            owner.set_password(password)
            owner.save(update_fields=["password"])
        caregiver, created = User.objects.get_or_create(
            username="caregiver@demo.invalid", defaults={"email": "caregiver@demo.invalid", "is_active": True}
        )
        if created:
            caregiver.set_password(password)
            caregiver.save(update_fields=["password"])
        existing_membership = owner.membership_set.filter(circle__name="Demo family").first()
        circle = (
            existing_membership.circle
            if existing_membership
            else create_circle(owner, "Demo family", "Asha", "Asia/Kolkata")
        )
        Membership.objects.get_or_create(
            circle=circle, user=caregiver, defaults={"role": Membership.Role.CAREGIVER}
        )
        now_local = timezone.now().astimezone(ZoneInfo(circle.timezone))
        due_soon = now_local + timedelta(minutes=2)
        due_before = now_local - timedelta(minutes=31)
        for title, when in [("Evening check-in", due_soon), ("Unacknowledged demo task", due_before)]:
            TaskTemplate.objects.get_or_create(
                circle=circle,
                title=title,
                defaults={
                    "category": TaskTemplate.Category.CARE,
                    "frequency": TaskTemplate.Frequency.DAILY,
                    "local_time": when.time().replace(second=0, microsecond=0),
                    "start_date": when.date(),
                    "assigned_to": caregiver,
                    "grace_minutes": 30,
                    "created_by": owner,
                },
            )
        result = scheduler_tick()
        self.stdout.write(
            self.style.SUCCESS(
                f"Circle {circle.pk} ready. Users: organizer@demo.invalid and caregiver@demo.invalid. Scheduler: {result}"
            )
        )

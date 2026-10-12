from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from care.models import Notification


class Command(BaseCommand):
    help = "Mark one pending notification as an expired worker lease for a recovery demo."

    def handle(self, *args, **options):
        item = Notification.objects.filter(status=Notification.Status.PENDING).order_by("pk").first()
        if item is None:
            raise CommandError("No pending notification. Run scheduler_tick first.")
        item.status = Notification.Status.PROCESSING
        item.lease_until = timezone.now() - timedelta(seconds=1)
        item.lease_token = "11111111-1111-1111-1111-111111111111"
        item.save(update_fields=["status", "lease_until", "lease_token"])
        self.stdout.write(
            f"Notification {item.pk} has an expired lease. Run deliver_notifications to recover it."
        )

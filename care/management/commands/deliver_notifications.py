from django.core.management.base import BaseCommand

from care.notifications import deliver_batch


class Command(BaseCommand):
    help = "Deliver a batch of due notifications, including expired worker leases."

    def handle(self, *args, **options):
        self.stdout.write(f"Processed {deliver_batch()} notifications")

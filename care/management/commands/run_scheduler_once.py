from django.core.management.base import BaseCommand

from care.scheduling import scheduler_tick


class Command(BaseCommand):
    help = "Run the scheduling pass once, useful for operations and demos."

    def handle(self, *args, **options):
        self.stdout.write(str(scheduler_tick()))

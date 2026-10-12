from celery import shared_task

from .notifications import deliver_batch
from .scheduling import scheduler_tick as run_tick


@shared_task(name="care.tasks.scheduler_tick")
def scheduler_tick():
    return run_tick()


@shared_task(name="care.tasks.deliver_notifications")
def deliver_notifications():
    return deliver_batch()

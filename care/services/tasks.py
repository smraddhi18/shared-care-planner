from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from ..models import Membership, Occurrence, TaskTemplate
from ..scheduling import generate_occurrences
from .access import membership_for
from .audit import audit

SCHEDULE_FIELDS = frozenset({"frequency", "weekdays", "local_time", "start_date", "active"})


def _require_schedule_editor(user, circle, current_category, requested_category):
    member = membership_for(user, circle, [Membership.Role.ORGANIZER, Membership.Role.CAREGIVER])
    if (
        TaskTemplate.Category.MEDICATION in (current_category, requested_category)
        and member.role != Membership.Role.ORGANIZER
    ):
        raise PermissionDenied("Only organizers can manage medication reminders")


def create_task(user, circle, values):
    _require_schedule_editor(user, circle, None, values.get("category", TaskTemplate.Category.CARE))
    with transaction.atomic():
        task = TaskTemplate.objects.create(circle=circle, created_by=user, **values)
        audit(circle, user, "task.created", task)
        generate_occurrences(horizon_days=7)
    return task


def update_task(user, task, changes):
    _require_schedule_editor(user, task.circle, task.category, changes.get("category", task.category))
    with transaction.atomic():
        for field, value in changes.items():
            setattr(task, field, value)
        task.save()
        if SCHEDULE_FIELDS.intersection(changes):
            Occurrence.objects.filter(
                template=task, state=Occurrence.State.PENDING, scheduled_for__gt=timezone.now()
            ).delete()
            if task.active:
                generate_occurrences(horizon_days=7)
        audit(task.circle, user, "task.updated", task, {"fields": sorted(changes)})
    return task

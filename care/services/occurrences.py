from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from ..models import Membership, Occurrence
from .access import membership_for
from .audit import audit
from .occurrence_actions import apply_occurrence_action


def update_occurrence(user, occurrence, action, snoozed_until=None):
    with transaction.atomic():
        occurrence = (
            Occurrence.objects.select_for_update().select_related("template__circle").get(pk=occurrence.pk)
        )
        member = membership_for(
            user, occurrence.template.circle, [Membership.Role.ORGANIZER, Membership.Role.CAREGIVER]
        )
        if member.role == Membership.Role.CAREGIVER and occurrence.template.assigned_to_id not in (
            None,
            user.pk,
        ):
            raise PermissionDenied("Task is assigned to another caregiver")
        selected_action = apply_occurrence_action(occurrence, action, snoozed_until, timezone.now())
        occurrence.save()
        audit(occurrence.template.circle, user, f"occurrence.{selected_action.value}", occurrence)
        return occurrence

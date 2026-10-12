from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from ..models import Membership
from .access import membership_for
from .audit import audit


def revoke_membership(user, circle, member_id):
    membership_for(user, circle, [Membership.Role.ORGANIZER])
    with transaction.atomic():
        member = get_object_or_404(
            Membership.objects.select_for_update(), pk=member_id, circle=circle, active=True
        )
        if (
            member.role == Membership.Role.ORGANIZER
            and Membership.objects.filter(circle=circle, role=Membership.Role.ORGANIZER, active=True).count()
            <= 1
        ):
            raise ValidationError({"member": "Cannot remove the last organizer"})
        member.active = False
        member.save(update_fields=["active"])
        audit(circle, user, "member.revoked", member)
    return member

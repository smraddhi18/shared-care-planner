from django.shortcuts import get_object_or_404

from ..models import CareCircle
from ..services.access import membership_for


def circle_access(user, circle_id, roles=None):
    circle = get_object_or_404(CareCircle, pk=circle_id, memberships__user=user, memberships__active=True)
    membership_for(user, circle, roles)
    return circle

from rest_framework.exceptions import PermissionDenied

from ..models import Membership


def membership_for(user, circle, roles=None):
    query = Membership.objects.filter(circle=circle, user=user, active=True)
    if roles:
        query = query.filter(role__in=roles)
    member = query.first()
    if member is None:
        raise PermissionDenied("Care circle access denied")
    return member

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..models import AuditEvent, Membership
from .common import circle_access
from .schemas import AuditEventSerializer


@extend_schema(responses=AuditEventSerializer(many=True), operation_id="list_audit_events")
@api_view(["GET"])
def audit_events(request, circle_id):
    circle = circle_access(request.user, circle_id, [Membership.Role.ORGANIZER])
    rows = AuditEvent.objects.filter(circle=circle).select_related("actor").order_by("-created_at")[:100]
    return Response(
        [
            {
                "action": row.action,
                "actor": row.actor.email if row.actor else None,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "created_at": row.created_at,
                "details": row.details,
            }
            for row in rows
        ]
    )

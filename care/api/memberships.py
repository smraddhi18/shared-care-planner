from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..models import Membership
from ..services.invitations import issue_invitation
from ..services.memberships import revoke_membership
from .common import circle_access
from .schemas import (
    InvitationRequestSerializer,
    InvitationResponseSerializer,
    MemberSerializer,
    StatusSerializer,
)


@extend_schema(
    request=InvitationRequestSerializer,
    responses={201: InvitationResponseSerializer},
    operation_id="invite_member",
)
@api_view(["POST"])
def invitations(request, circle_id):
    circle = circle_access(request.user, circle_id, [Membership.Role.ORGANIZER])
    serializer = InvitationRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    invite = issue_invitation(
        request.user,
        circle,
        serializer.validated_data["email"],
        serializer.validated_data["role"],
    )
    return Response(
        {"id": invite.pk, "email": invite.email, "role": invite.role, "expires_at": invite.expires_at},
        status=status.HTTP_201_CREATED,
    )


@extend_schema(responses=MemberSerializer(many=True), operation_id="list_members")
@api_view(["GET"])
def members(request, circle_id):
    circle = circle_access(request.user, circle_id)
    rows = Membership.objects.filter(circle=circle, active=True).select_related("user")
    return Response(
        [{"id": row.pk, "user_id": row.user_id, "email": row.user.email, "role": row.role} for row in rows]
    )


@extend_schema(request=None, responses=StatusSerializer, operation_id="revoke_member")
@api_view(["POST"])
def revoke_member(request, circle_id, member_id):
    circle = circle_access(request.user, circle_id, [Membership.Role.ORGANIZER])
    revoke_membership(request.user, circle, member_id)
    return Response({"status": "revoked"})

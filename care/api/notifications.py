from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..models import Notification
from ..serializers import NotificationSerializer
from .common import circle_access
from .schemas import StatusSerializer


@extend_schema(responses=NotificationSerializer(many=True), operation_id="list_notifications")
@api_view(["GET"])
def notifications(request, circle_id):
    circle = circle_access(request.user, circle_id)
    rows = Notification.objects.filter(
        circle=circle,
        recipient=request.user,
        channel=Notification.Channel.IN_APP,
        status=Notification.Status.SENT,
    ).order_by("-created_at")[:50]
    return Response(NotificationSerializer(rows, many=True).data)


@extend_schema(request=None, responses=StatusSerializer, operation_id="mark_notification_read")
@api_view(["POST"])
def mark_notification_read(request, notification_id):
    item = get_object_or_404(
        Notification,
        pk=notification_id,
        recipient=request.user,
        channel=Notification.Channel.IN_APP,
        status=Notification.Status.SENT,
    )
    circle_access(request.user, item.circle_id)
    item.read_at = timezone.now()
    item.save(update_fields=["read_at"])
    return Response({"status": "read"})

from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..models import Occurrence
from ..serializers import OccurrenceSerializer
from ..services.occurrences import update_occurrence
from .common import circle_access
from .schemas import OccurrenceActionSerializer


@extend_schema(responses=OccurrenceSerializer(many=True), operation_id="list_occurrences")
@api_view(["GET"])
def occurrences(request, circle_id):
    circle = circle_access(request.user, circle_id)
    rows = (
        Occurrence.objects.filter(
            template__circle=circle,
            scheduled_for__gte=timezone.now() - timedelta(days=1),
            scheduled_for__lte=timezone.now() + timedelta(days=8),
        )
        .select_related("template")
        .order_by("scheduled_for")[:200]
    )
    return Response(OccurrenceSerializer(rows, many=True).data)


@extend_schema(
    request=OccurrenceActionSerializer, responses=OccurrenceSerializer, operation_id="act_on_occurrence"
)
@api_view(["POST"])
def occurrence_action(request, occurrence_id):
    occurrence = get_object_or_404(Occurrence.objects.select_related("template__circle"), pk=occurrence_id)
    circle_access(request.user, occurrence.template.circle_id)
    serializer = OccurrenceActionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    occurrence = update_occurrence(
        request.user,
        occurrence,
        serializer.validated_data["action"],
        serializer.validated_data.get("snoozed_until"),
    )
    return Response(OccurrenceSerializer(occurrence).data)

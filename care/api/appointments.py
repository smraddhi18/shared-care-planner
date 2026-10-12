from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..models import Appointment
from ..serializers import AppointmentSerializer
from ..services.appointments import create_appointment, update_appointment
from .common import circle_access


@extend_schema(methods=["GET"], responses=AppointmentSerializer(many=True), operation_id="list_appointments")
@extend_schema(
    methods=["POST"],
    request=AppointmentSerializer,
    responses={201: AppointmentSerializer},
    operation_id="create_appointment",
)
@api_view(["GET", "POST"])
def appointments(request, circle_id):
    circle = circle_access(request.user, circle_id)
    if request.method == "GET":
        rows = Appointment.objects.filter(
            circle=circle, starts_at__gte=timezone.now() - timedelta(days=1)
        ).order_by("starts_at")[:100]
        return Response(AppointmentSerializer(rows, many=True).data)
    serializer = AppointmentSerializer(data=request.data, context={"circle": circle})
    serializer.is_valid(raise_exception=True)
    appointment = create_appointment(request.user, circle, serializer.validated_data)
    return Response(AppointmentSerializer(appointment).data, status=status.HTTP_201_CREATED)


@extend_schema(methods=["GET"], responses=AppointmentSerializer, operation_id="get_appointment")
@extend_schema(
    methods=["PATCH"],
    request=AppointmentSerializer,
    responses=AppointmentSerializer,
    operation_id="update_appointment",
)
@api_view(["GET", "PATCH"])
def appointment_detail(request, circle_id, appointment_id):
    circle = circle_access(request.user, circle_id)
    appointment = get_object_or_404(Appointment, pk=appointment_id, circle=circle)
    if request.method == "GET":
        return Response(AppointmentSerializer(appointment).data)
    serializer = AppointmentSerializer(
        appointment, data=request.data, partial=True, context={"circle": circle}
    )
    serializer.is_valid(raise_exception=True)
    appointment = update_appointment(request.user, appointment, serializer.validated_data)
    return Response(AppointmentSerializer(appointment).data)

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..models import CareCircle
from ..serializers import CircleSerializer
from ..services.circles import create_circle
from .common import circle_access


@extend_schema(methods=["GET"], responses=CircleSerializer(many=True), operation_id="list_circles")
@extend_schema(
    methods=["POST"],
    request=CircleSerializer,
    responses={201: CircleSerializer},
    operation_id="create_circle",
)
@api_view(["GET", "POST"])
def circles(request):
    if request.method == "GET":
        rows = CareCircle.objects.filter(memberships__user=request.user, memberships__active=True).order_by(
            "name"
        )
        return Response(CircleSerializer(rows, many=True).data)
    serializer = CircleSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    circle = create_circle(
        request.user,
        serializer.validated_data["name"],
        serializer.validated_data["recipient_display_name"],
        serializer.validated_data["timezone"],
    )
    return Response(CircleSerializer(circle).data, status=status.HTTP_201_CREATED)


@extend_schema(responses=CircleSerializer, operation_id="get_circle")
@api_view(["GET"])
def circle_detail(request, circle_id):
    circle = circle_access(request.user, circle_id)
    return Response(CircleSerializer(circle).data)

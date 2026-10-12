from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..models import TaskTemplate
from ..serializers import TaskSerializer
from ..services.tasks import create_task, update_task
from .common import circle_access


@extend_schema(methods=["GET"], responses=TaskSerializer(many=True), operation_id="list_tasks")
@extend_schema(
    methods=["POST"], request=TaskSerializer, responses={201: TaskSerializer}, operation_id="create_task"
)
@api_view(["GET", "POST"])
def tasks(request, circle_id):
    circle = circle_access(request.user, circle_id)
    if request.method == "GET":
        rows = TaskTemplate.objects.filter(circle=circle).order_by("id")
        return Response(TaskSerializer(rows, many=True).data)
    serializer = TaskSerializer(data=request.data, context={"circle": circle})
    serializer.is_valid(raise_exception=True)
    task = create_task(request.user, circle, serializer.validated_data)
    return Response(TaskSerializer(task).data, status=status.HTTP_201_CREATED)


@extend_schema(methods=["GET"], responses=TaskSerializer, operation_id="get_task")
@extend_schema(
    methods=["PATCH"], request=TaskSerializer, responses=TaskSerializer, operation_id="update_task"
)
@api_view(["GET", "PATCH"])
def task_detail(request, circle_id, task_id):
    circle = circle_access(request.user, circle_id)
    task = get_object_or_404(TaskTemplate, pk=task_id, circle=circle)
    if request.method == "GET":
        return Response(TaskSerializer(task).data)
    serializer = TaskSerializer(task, data=request.data, partial=True, context={"circle": circle})
    serializer.is_valid(raise_exception=True)
    task = update_task(request.user, task, serializer.validated_data)
    return Response(TaskSerializer(task).data)

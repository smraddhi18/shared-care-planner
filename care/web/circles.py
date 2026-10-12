from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from ..models import CareCircle, Membership, Notification, Occurrence
from ..services.access import membership_for
from ..services.circles import create_circle


@login_required
@require_http_methods(["GET", "POST"])
def dashboard(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        recipient = request.POST.get("recipient_display_name", "").strip()
        zone = request.POST.get("timezone", "Asia/Kolkata").strip()
        if not name or not recipient or len(name) > 120 or len(recipient) > 120:
            messages.error(request, "Enter a circle name and a display name, each under 120 characters.")
        else:
            try:
                circle = create_circle(request.user, name, recipient, zone)
                return redirect("circle_page", circle_id=circle.pk)
            except ValidationError:
                messages.error(request, "Choose a valid time zone.")
    circles = CareCircle.objects.filter(memberships__user=request.user, memberships__active=True).order_by(
        "name"
    )
    return render(request, "care/dashboard.html", {"circles": circles})


@login_required
@require_http_methods(["GET"])
def circle_page(request, circle_id):
    circle = get_object_or_404(
        CareCircle, pk=circle_id, memberships__user=request.user, memberships__active=True
    )
    member = membership_for(request.user, circle)
    tasks = circle.tasks.select_related("assigned_to").order_by("-active", "id")
    appointments = circle.appointments.filter(starts_at__gte=timezone.now() - timedelta(days=1)).order_by(
        "starts_at"
    )[:20]
    occurrences = (
        Occurrence.objects.filter(
            template__circle=circle,
            scheduled_for__gte=timezone.now() - timedelta(days=1),
            scheduled_for__lte=timezone.now() + timedelta(days=8),
        )
        .select_related("template")
        .order_by("scheduled_for")[:50]
    )
    members = Membership.objects.filter(circle=circle, active=True).select_related("user")
    notifications = Notification.objects.filter(
        circle=circle,
        recipient=request.user,
        channel=Notification.Channel.IN_APP,
        status=Notification.Status.SENT,
    ).order_by("-created_at")[:20]
    return render(
        request,
        "care/circle.html",
        {
            "circle": circle,
            "member": member,
            "tasks": tasks,
            "appointments": appointments,
            "occurrences": occurrences,
            "members": members,
            "notifications": notifications,
        },
    )

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..models import Notification


def livez(_request):
    return JsonResponse({"status": "live"})


def readyz(_request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        cache.set("readiness", "ok", timeout=10)
        if cache.get("readiness") != "ok":
            raise RuntimeError("Cache unavailable")
        return JsonResponse({"status": "ready"})
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)


@login_required
@require_http_methods(["GET"])
def metrics(request):
    if not request.user.is_staff:
        return JsonResponse({"error": "forbidden"}, status=403)
    counts = {
        status: Notification.objects.filter(status=status).count()
        for status, _ in Notification.Status.choices
    }
    oldest = (
        Notification.objects.filter(status=Notification.Status.PENDING)
        .order_by("created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    return JsonResponse(
        {
            "notification_counts": counts,
            "oldest_pending_seconds": int((timezone.now() - oldest).total_seconds()) if oldest else 0,
            "generated_at": timezone.now().isoformat(),
        }
    )

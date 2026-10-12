from django.urls import path

from .api import appointments, audit, circles, memberships, notifications, occurrences, tasks

urlpatterns = [
    path("circles/", circles.circles),
    path("circles/<int:circle_id>/", circles.circle_detail),
    path("circles/<int:circle_id>/tasks/", tasks.tasks),
    path("circles/<int:circle_id>/tasks/<int:task_id>/", tasks.task_detail),
    path("circles/<int:circle_id>/appointments/", appointments.appointments),
    path("circles/<int:circle_id>/appointments/<int:appointment_id>/", appointments.appointment_detail),
    path("circles/<int:circle_id>/occurrences/", occurrences.occurrences),
    path("occurrences/<int:occurrence_id>/actions/", occurrences.occurrence_action),
    path("circles/<int:circle_id>/invitations/", memberships.invitations),
    path("circles/<int:circle_id>/members/", memberships.members),
    path("circles/<int:circle_id>/members/<int:member_id>/revoke/", memberships.revoke_member),
    path("circles/<int:circle_id>/notifications/", notifications.notifications),
    path("notifications/<int:notification_id>/read/", notifications.mark_notification_read),
    path("circles/<int:circle_id>/audit/", audit.audit_events),
]

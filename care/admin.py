from django.contrib import admin

from .models import (
    Appointment,
    AuditEvent,
    CareCircle,
    EmailVerification,
    Invitation,
    Membership,
    Notification,
    Occurrence,
    TaskTemplate,
)

for model in (
    CareCircle,
    Membership,
    Invitation,
    EmailVerification,
    TaskTemplate,
    Appointment,
    Occurrence,
    Notification,
    AuditEvent,
):
    admin.site.register(model)

from ..models import AuditEvent


def audit(circle, actor, action, target, details=None):
    AuditEvent.objects.create(
        circle=circle,
        actor=actor,
        action=action,
        target_type=type(target).__name__,
        target_id=str(target.pk),
        details=details or {},
    )

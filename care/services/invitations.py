import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from ..models import Invitation, Membership
from .access import membership_for
from .audit import audit


def create_invite(user, circle, email, role):
    membership_for(user, circle, [Membership.Role.ORGANIZER])
    email = email.strip().lower()
    if role not in (Membership.Role.CAREGIVER, Membership.Role.VIEWER):
        raise ValidationError({"role": "Only caregiver or viewer can be invited"})
    if Membership.objects.filter(circle=circle, user__email__iexact=email, active=True).exists():
        raise ValidationError({"email": "User is already a member"})
    token = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        circle=circle,
        email=email,
        role=role,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=timezone.now() + timedelta(hours=48),
        created_by=user,
    )
    audit(circle, user, "invite.created", invitation, {"role": role})
    return invitation, token


def accept_invitation(user, token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with transaction.atomic():
        invite = Invitation.objects.select_for_update().filter(token_hash=token_hash).first()
        if invite is None or invite.accepted_at or invite.expires_at <= timezone.now():
            raise ValidationError({"invite": "Invite is invalid or expired"})
        if user.email.lower() != invite.email.lower():
            raise PermissionDenied("Invite belongs to another email address")
        member, _ = Membership.objects.update_or_create(
            circle=invite.circle, user=user, defaults={"role": invite.role, "active": True}
        )
        invite.accepted_at = timezone.now()
        invite.save(update_fields=["accepted_at"])
        audit(invite.circle, user, "invite.accepted", member)
        return invite.circle


def issue_invitation(user, circle, email, role):
    invite, token = create_invite(user, circle, email, role)
    link = f"{settings.PUBLIC_BASE_URL}/invite/{token}/"
    send_mail(
        "Shared Care Planner invitation",
        f"You have been invited to a care circle. Accept: {link}",
        settings.DEFAULT_FROM_EMAIL,
        [invite.email],
        fail_silently=False,
    )
    return invite

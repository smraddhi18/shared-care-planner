import hashlib
import secrets
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST
from rest_framework.exceptions import PermissionDenied, ValidationError

from ..models import EmailVerification
from ..services.invitations import accept_invitation

User = get_user_model()


class SignupForm(UserCreationForm):
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ("email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("This email is already registered")
        return email


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        token = secrets.token_urlsafe(32)
        with transaction.atomic():
            user = form.save(commit=False)
            user.username = form.cleaned_data["email"]
            user.email = form.cleaned_data["email"]
            user.is_active = False
            user.save()
            EmailVerification.objects.create(
                user=user,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=timezone.now() + timedelta(hours=24),
            )
            link = f"{settings.PUBLIC_BASE_URL}/verify/{token}/"
            send_mail(
                "Verify your Shared Care Planner account",
                f"Open this link to verify your email: {link}",
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
        if request.POST.get("invite"):
            request.session["pending_invite"] = request.POST["invite"]
        return render(
            request,
            "care/message.html",
            {"title": "Check your email", "body": "Use the verification link to activate your account."},
        )
    return render(request, "care/signup.html", {"form": form, "invite": request.GET.get("invite", "")})


@require_http_methods(["GET"])
def verify_email(request, token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with transaction.atomic():
        record = (
            EmailVerification.objects.select_for_update()
            .select_related("user")
            .filter(token_hash=token_hash)
            .first()
        )
        if not record or record.used_at or record.expires_at <= timezone.now():
            return render(
                request,
                "care/message.html",
                {"title": "Link unavailable", "body": "This verification link is invalid or expired."},
                status=400,
            )
        record.used_at = timezone.now()
        record.save(update_fields=["used_at"])
        user = record.user
        user.is_active = True
        user.save(update_fields=["is_active"])
    auth_login(request, user)
    invite = request.session.pop("pending_invite", None)
    return redirect("accept_invite", token=invite) if invite else redirect("dashboard")


@require_http_methods(["GET", "POST"])
def resend_verification(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        rate_key = "verification:" + hashlib.sha256(email.encode()).hexdigest()
        if email and cache.add(rate_key, "1", timeout=60):
            user = User.objects.filter(email__iexact=email, is_active=False).first()
            if user:
                token = secrets.token_urlsafe(32)
                EmailVerification.objects.update_or_create(
                    user=user,
                    defaults={
                        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                        "expires_at": timezone.now() + timedelta(hours=24),
                        "used_at": None,
                    },
                )
                link = f"{settings.PUBLIC_BASE_URL}/verify/{token}/"
                send_mail(
                    "Verify your Shared Care Planner account",
                    f"Open this link to verify your email: {link}",
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )
        return render(
            request,
            "care/message.html",
            {
                "title": "Check your email",
                "body": "If an inactive account exists, a new verification link has been sent.",
            },
        )
    return render(request, "care/resend_verification.html")


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = AuthenticationForm(request, data=request.POST or None)
    login_key = (
        "login:"
        + hashlib.sha256(
            (request.META.get("REMOTE_ADDR", "") + ":" + request.POST.get("username", "").lower()).encode()
        ).hexdigest()
    )
    if request.method == "POST" and cache.get(login_key, 0) >= 5:
        form.add_error(None, "Too many attempts. Try again in 15 minutes.")
        return render(
            request, "care/login.html", {"form": form, "next": request.GET.get("next", "")}, status=429
        )
    if request.method == "POST" and form.is_valid():
        cache.delete(login_key)
        auth_login(request, form.get_user())
        next_url = request.POST.get("next", "")
        if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect("dashboard")
    if request.method == "POST":
        cache.set(login_key, cache.get(login_key, 0) + 1, timeout=900)
    return render(request, "care/login.html", {"form": form, "next": request.GET.get("next", "")})


@require_POST
def logout_view(request):
    auth_logout(request)
    return redirect("login")


@require_http_methods(["GET", "POST"])
def accept_invite(request, token):
    if not request.user.is_authenticated:
        return render(request, "care/invite.html", {"token": token})
    if request.method == "POST":
        try:
            circle = accept_invitation(request.user, token)
            return redirect("circle_page", circle_id=circle.pk)
        except (ValidationError, PermissionDenied) as exc:
            return render(
                request,
                "care/message.html",
                {"title": "Cannot accept invitation", "body": str(exc)},
                status=400,
            )
    return render(request, "care/invite.html", {"token": token})

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from care.web import accounts, circles, health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", circles.dashboard, name="dashboard"),
    path("signup/", accounts.signup, name="signup"),
    path("verify/<str:token>/", accounts.verify_email, name="verify_email"),
    path("login/", accounts.login_view, name="login"),
    path("resend-verification/", accounts.resend_verification, name="resend_verification"),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="care/password_reset.html",
            email_template_name="care/password_reset_email.txt",
            success_url="/password-reset/sent/",
        ),
        name="password_reset",
    ),
    path(
        "password-reset/sent/",
        auth_views.PasswordResetDoneView.as_view(template_name="care/password_reset_sent.html"),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="care/password_reset_confirm.html",
            success_url="/password-reset/complete/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(template_name="care/password_reset_complete.html"),
        name="password_reset_complete",
    ),
    path("logout/", accounts.logout_view, name="logout"),
    path("circle/<int:circle_id>/", circles.circle_page, name="circle_page"),
    path("invite/<str:token>/", accounts.accept_invite, name="accept_invite"),
    path("api/v1/", include("care.api_urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("livez/", health.livez),
    path("readyz/", health.readyz),
    path("metrics/", health.metrics),
]

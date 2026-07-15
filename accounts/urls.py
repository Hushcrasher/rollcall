from django.contrib.auth import views as auth_views
from django.urls import URLPattern, URLResolver, path, reverse_lazy

from accounts import views

app_name = "accounts"

urlpatterns: list[URLPattern | URLResolver] = [
    # Signup + email verification (the gate to contributing)
    path("signup/", views.SignupView.as_view(), name="signup"),
    path("verify-email/sent/", views.VerificationSentView.as_view(), name="verification_sent"),
    path("verify-email/resend/", views.resend_verification, name="resend_verification"),
    path("verify-email/<uidb64>/<token>/", views.verify_email, name="verify_email"),
    # Login / logout
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=views.EmailAuthenticationForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Password reset flow (Django's built-in views + our templates)
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="accounts/password_reset.html",
            email_template_name="accounts/email/password_reset_email.txt",
            subject_template_name="accounts/email/password_reset_subject.txt",
            success_url=reverse_lazy("accounts:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    # Recruiter application (approved manually in the admin)
    path("recruiters/apply/", views.RecruiterApplyView.as_view(), name="recruiter_apply"),
    # Settings + GDPR (deletion, export)
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("settings/delete/", views.AccountDeleteView.as_view(), name="account_delete"),
    path("settings/export/", views.export_personal_data, name="export_data"),
    path("u/<slug:slug>/github/", views.github_activity, name="github_activity"),
    # Public profile — kept last so it never shadows the fixed routes above.
    path("u/<slug:slug>/", views.ProfileView.as_view(), name="profile"),
]

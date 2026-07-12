"""Transactional emails. Dev uses the console backend; prod wires Brevo."""

from django.http import HttpRequest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext as _

from accounts.models import User
from accounts.tokens import email_verification_token


def send_verification_email(request: HttpRequest, user: User) -> None:
    path = reverse(
        "accounts:verify_email",
        kwargs={
            "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": email_verification_token.make_token(user),
        },
    )
    body = render_to_string(
        "accounts/email/verify_email.txt",
        {"user": user, "verify_url": request.build_absolute_uri(path)},
    )
    user.email_user(_("Verify your email for Rollcall"), body)

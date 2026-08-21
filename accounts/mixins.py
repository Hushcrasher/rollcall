"""Access-control mixins shared across apps."""

from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _


class EmailVerifiedRequiredMixin(LoginRequiredMixin):
    """Bounce logged-in-but-unverified users to the verification notice.

    Guards the surfaces the email-verified rule (docs/00 non-negotiable #6,
    docs/01 §3.4 "first anti-spam line") protects: creating credits, the
    contact relay — outbound mail carrying a sender-controlled Reply-To — and
    portfolio uploads, which put attacker-chosen bytes in the media bucket.
    Views set `verification_message` to say what verifying unlocks.
    """

    request: Any  # provided by the Django CBV this is mixed into

    verification_message = _("Please verify your email first.")

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        user = self.request.user
        if user.is_authenticated and not user.is_email_verified:
            messages.error(request, self.verification_message)
            return redirect("accounts:verification_sent")
        return super().dispatch(request, *args, **kwargs)

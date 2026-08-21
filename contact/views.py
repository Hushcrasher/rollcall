"""Contact relay — the person's email is NEVER exposed. We email them directly
with Reply-To = the sender, so they can choose to reply off-platform. Per-sender
rate limiting is backed by the contact_requests table (also the abuse trail)."""

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.mail import EmailMessage
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.views.generic import CreateView, FormView

from accounts.mixins import EmailVerifiedRequiredMixin
from accounts.models import User
from contact.forms import ContactForm, ReportForm
from contact.models import ContactRequest, Report

_DEFAULT_RATE_LIMIT = 20


class ContactView(EmailVerifiedRequiredMixin, FormView):
    template_name = "contact/contact_form.html"
    form_class = ContactForm
    target: User
    # The relay sends mail from our domain with Reply-To = the sender's
    # address; verification is what proves they own it. Lazy: a class
    # attribute evaluates at import time, and plain gettext() would bake in
    # whatever language happened to be active then (accounts/mixins.py's
    # base class attribute is lazy for the same reason).
    verification_message = _lazy("Please verify your email before contacting members.")

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # 404 unless the target exists, is public, and is contactable.
        self.target = get_object_or_404(
            User, slug=kwargs["slug"], profile_public=True, contactable=True
        )
        if self.request.user.is_authenticated and self.target == self.request.user:
            raise Http404  # you can't contact yourself
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["target"] = self.target  # display_name only — never the email
        return context

    def form_valid(self, form: ContactForm) -> HttpResponse:
        sender = self.request.user
        if self._rate_limited(sender):
            messages.error(
                self.request, _("You've reached today's contact limit. Try again tomorrow.")
            )
            return redirect(self.target.get_absolute_url())

        subject = form.cleaned_data["subject"]
        message = form.cleaned_data["message"]
        ContactRequest.objects.create(
            sender=sender, recipient=self.target, subject=subject, message=message
        )
        self._send(sender, subject, message)
        messages.success(self.request, _("Your message was sent."))
        return redirect(self.target.get_absolute_url())

    def _rate_limited(self, sender: User) -> bool:
        limit = getattr(settings, "CONTACT_RATE_LIMIT_PER_DAY", _DEFAULT_RATE_LIMIT)
        since = timezone.now() - timedelta(days=1)
        recent = ContactRequest.objects.filter(sender=sender, sent_at__gte=since).count()
        return recent >= limit

    def _send(self, sender: User, subject: str, message: str) -> None:
        body = render_to_string(
            "contact/email/contact_message.txt",
            {"sender": sender, "message": message, "target": self.target},
        )
        EmailMessage(
            subject=f"[Rollcall] {subject}",
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[self.target.email],  # used only to deliver; never rendered
            reply_to=[sender.email],  # replies reach the sender directly
        ).send()


class ReportView(LoginRequiredMixin, CreateView):
    """Signal anything for private moderation (docs/04 §11). Handled in the
    admin. There is no public accusatory content anywhere by design."""

    model = Report
    form_class = ReportForm
    template_name = "contact/report_form.html"
    success_url = reverse_lazy("accounts:account")

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        target_type = self.request.GET.get("type")
        target_id = self.request.GET.get("id")
        if target_type:
            initial["target_type"] = target_type
        if target_id and target_id.isdigit():
            initial["target_id"] = int(target_id)
        return initial

    def form_valid(self, form: ReportForm) -> HttpResponse:
        form.instance.reporter = self.request.user
        messages.success(self.request, _("Thanks — your report was submitted for review."))
        return super().form_valid(form)

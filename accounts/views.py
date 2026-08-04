"""Account views — signup, email verification, login helpers, profile,
account, and GDPR (deletion + export)."""

import logging
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, FormView, TemplateView, UpdateView
from django_ratelimit.decorators import ratelimit

from accounts.emails import send_verification_email
from accounts.export import build_personal_data_export
from accounts.forms import (
    EmailAuthenticationForm,
    RecruiterApplicationForm,
    SettingsForm,
    SignupForm,
)
from accounts.github import get_github_activity
from accounts.http import AuthedHttpRequest
from accounts.models import RecruiterApplication, User
from accounts.tokens import email_verification_token
from contributions.models import Contribution

logger = logging.getLogger(__name__)

__all__ = [
    "AccountDeleteView",
    "AccountView",
    "EmailAuthenticationForm",
    "ProfileView",
    "RecruiterApplyView",
    "SignupView",
    "VerificationSentView",
    "export_personal_data",
    "github_activity",
    "my_profile_redirect",
    "resend_verification",
    "verify_email",
]


def _profile_rate(group: str, request: HttpRequest) -> str:
    return settings.PROFILE_RATELIMIT


def _visible_users(request: HttpRequest) -> QuerySet[User]:
    """Profiles the requester may see: public ones, plus their own."""
    if request.user.is_authenticated:  # ty: ignore[unresolved-attribute]
        return User.objects.filter(Q(profile_public=True) | Q(pk=request.user.pk))  # ty: ignore[unresolved-attribute]
    return User.objects.filter(profile_public=True)


@login_required
def my_profile_redirect(request: AuthedHttpRequest) -> HttpResponse:
    """Slugless entry point to one's own profile. LOGIN_REDIRECT_URL is a plain
    string setting and cannot pass a slug to reverse(), so the slug is resolved
    here at request time instead."""
    return redirect(request.user.get_absolute_url())


class SignupView(FormView):
    template_name = "accounts/signup.html"
    form_class = SignupForm

    def form_valid(self, form: SignupForm) -> HttpResponse:
        user = form.save()
        send_verification_email(self.request, user)
        # Auto-login: the gate is on creating contributions, not on logging in.
        login(self.request, user)
        return redirect("accounts:verification_sent")


class VerificationSentView(TemplateView):
    template_name = "accounts/verification_sent.html"


def _user_from_uidb64(uidb64: str) -> User | None:
    try:
        pk = force_str(urlsafe_base64_decode(uidb64))
        return User.objects.get(pk=pk)
    except (TypeError, ValueError, OverflowError, ObjectDoesNotExist):
        return None


def verify_email(request: HttpRequest, uidb64: str, token: str) -> HttpResponse:
    user = _user_from_uidb64(uidb64)
    if user is not None and email_verification_token.check_token(user, token):
        if user.email_verified_at is None:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
        messages.success(request, _("Your email is verified — you can now add credits."))
        return redirect("accounts:account")
    messages.error(request, _("This verification link is invalid or has expired."))
    return render(request, "accounts/verify_email_invalid.html")


@require_POST
@login_required
def resend_verification(request: AuthedHttpRequest) -> HttpResponse:
    user = request.user
    if user.email_verified_at is None:
        send_verification_email(request, user)
        messages.success(request, _("Verification email sent."))
        return redirect("accounts:verification_sent")
    return redirect("accounts:account")


@method_decorator(ratelimit(key="ip", rate=_profile_rate, method="GET", block=True), name="get")
class ProfileView(DetailView):
    template_name = "accounts/profile.html"
    context_object_name = "profile_user"

    def get_queryset(self) -> QuerySet[User]:
        # Honor profile_public: a non-public profile is visible only to its owner.
        return _visible_users(self.request)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["contributions"] = (
            Contribution.objects.filter(user=self.object, status=Contribution.Status.ACTIVE)
            .select_related("game", "company", "discipline")
            .order_by("-start_date")
        )
        return context


class AccountView(LoginRequiredMixin, UpdateView):
    form_class = SettingsForm
    template_name = "accounts/account.html"
    success_url = reverse_lazy("accounts:account")

    def get_object(self, queryset: QuerySet[User] | None = None) -> User:
        return self.request.user

    def form_valid(self, form: SettingsForm) -> HttpResponse:
        messages.success(self.request, _("Your settings were saved."))
        return super().form_valid(form)


class AccountDeleteView(LoginRequiredMixin, TemplateView):
    """Confirm, then hard-delete: contributions cascade, vouches emitted are
    anonymized (FK rules), and the avatar object is removed (GDPR §14)."""

    template_name = "accounts/account_delete.html"

    def post(self, request: AuthedHttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        user = request.user
        # avatar is a FieldFile at runtime; the type checker sees the ImageField.
        avatar: Any = user.avatar
        if avatar:
            avatar.delete(save=False)  # FK deletion doesn't remove files
        logout(request)
        user.delete()
        messages.success(request, _("Your account and all your credits were deleted."))
        return redirect("accounts:login")


class RecruiterApplyView(LoginRequiredMixin, CreateView):
    """Members apply to become recruiters; an admin approves manually (§3.6)."""

    model = RecruiterApplication
    form_class = RecruiterApplicationForm
    template_name = "accounts/recruiter_apply.html"
    success_url = reverse_lazy("accounts:account")

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        user = self.request.user
        if user.is_authenticated:
            if user.is_recruiter:
                return redirect("search:recruiter_search")
            pending = RecruiterApplication.objects.filter(
                user=user, status=RecruiterApplication.Status.PENDING
            ).exists()
            if pending:
                messages.info(request, _("Your recruiter application is already under review."))
                return redirect("accounts:account")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form: RecruiterApplicationForm) -> HttpResponse:
        form.instance.user = self.request.user
        messages.success(self.request, _("Application submitted — we'll review it soon."))
        return super().form_valid(form)


@login_required
def export_personal_data(request: AuthedHttpRequest) -> JsonResponse:
    response = JsonResponse(
        build_personal_data_export(request.user), json_dumps_params={"indent": 2}
    )
    response["Content-Disposition"] = 'attachment; filename="rollcall-my-data.json"'
    return response


@ratelimit(key="ip", rate=_profile_rate, method="GET", block=True)
def github_activity(request: HttpRequest, slug: str) -> HttpResponse:
    """htmx fragment: a member's public GitHub activity. Never 500s — any
    failure degrades to a quiet state so the profile page is unaffected."""
    profile_user = _visible_users(request).filter(slug=slug).first()
    if profile_user is None:
        raise Http404
    activity = None
    try:
        activity = get_github_activity(profile_user)
    except Exception:  # noqa: BLE001 — the block must never break the page
        logger.exception("GitHub activity block failed for %s", slug)
    return render(request, "accounts/_github_block.html", {"activity": activity})

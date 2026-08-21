"""Account views — signup, email verification, login helpers, profile,
account, and GDPR (deletion + export)."""

import logging
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, FormView, TemplateView, UpdateView
from django_ratelimit.decorators import ratelimit

from accounts.emails import send_verification_email
from accounts.export import build_personal_data_export
from accounts.forms import (
    EmailAuthenticationForm,
    PortfolioImageForm,
    ProfileForm,
    RecruiterApplicationForm,
    SignupForm,
)
from accounts.github import get_github_activity
from accounts.http import AuthedHttpRequest
from accounts.mixins import EmailVerifiedRequiredMixin
from accounts.models import MAX_PORTFOLIO_IMAGES, ProfileImage, RecruiterApplication, User
from accounts.registration import create_and_login
from accounts.tokens import email_verification_token
from contributions.models import Contribution

logger = logging.getLogger(__name__)

__all__ = [
    "AccountDeleteView",
    "AccountView",
    "EmailAuthenticationForm",
    "PortfolioAddView",
    "PortfolioDeleteView",
    "ProfileEditView",
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
        create_and_login(self.request, form)
        return redirect("accounts:verification_sent")


class VerificationSentView(TemplateView):
    template_name = "accounts/verification_sent.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        # Named so the verification click collects something rather than lifting
        # a restriction — it is the declare funnel's last exit.
        user: Any = self.request.user
        context["pending_credit"] = (
            Contribution.objects.filter(user=user, status=Contribution.Status.PENDING)
            .select_related("game")
            .order_by("-id")
            .first()
            if user.is_authenticated
            else None
        )
        return context


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
        # Publish anything the declare funnel parked before verification. update()
        # returns the row count, which is also how we know what to say.
        published = Contribution.objects.filter(
            user=user, status=Contribution.Status.PENDING
        ).update(status=Contribution.Status.ACTIVE)
        if published:
            messages.success(
                request, _("Your email is verified — your credit is now live on your profile.")
            )
        else:
            messages.success(request, _("Your email is verified — you can now add credits."))
        return redirect("accounts:my_profile")
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
        # `?preview=member` is honored for the owner only — for anyone else this
        # already *is* the member view, so the param can never change what a
        # third party sees.
        user: Any = self.request.user
        is_self = user.is_authenticated and user.pk == self.object.pk
        preview = is_self and self.request.GET.get("preview") == "member"
        context["is_owner"] = is_self and not preview
        context["preview"] = preview
        context["is_visitor"] = user.is_authenticated and not is_self
        # profile_public=False hides the member everywhere but is invisible to
        # them, since _visible_users exempts the owner. Shown in the preview too.
        context["private_notice"] = is_self and not self.object.profile_public
        context["portfolio_images"] = self.object.portfolio_images.all()
        return context


class ProfileEditView(LoginRequiredMixin, UpdateView):
    """The profile fields. Slugless: the object is always the requester, so a
    slug in the URL could only ever disagree with it."""

    form_class = ProfileForm
    template_name = "accounts/profile_edit.html"

    def get_object(self, queryset: QuerySet[User] | None = None) -> User:
        return self.request.user

    def get_success_url(self) -> str:
        # Land on the profile so the member sees the result of the edit.
        return str(self.object.get_absolute_url())

    def form_valid(self, form: ProfileForm) -> HttpResponse:
        messages.success(self.request, _("Your profile was saved."))
        return super().form_valid(form)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["portfolio_images"] = self.request.user.portfolio_images.all()
        context["portfolio_form"] = PortfolioImageForm()
        context["max_portfolio_images"] = MAX_PORTFOLIO_IMAGES
        return context


# Named group, house rule: an unnamed decorator derives its group from the
# view's qualname, so a rename would silently move the counter.
_PORTFOLIO_RATELIMIT_GROUP = "portfolio_add"


@method_decorator(
    ratelimit(group=_PORTFOLIO_RATELIMIT_GROUP, key="user", rate="10/h", method="POST", block=True),
    name="post",
)
class PortfolioAddView(EmailVerifiedRequiredMixin, View):
    # Lazy: a class attribute evaluates at import time, and plain gettext()
    # would bake in whatever language happened to be active then
    # (accounts/mixins.py's base class attribute is lazy for the same reason).
    verification_message = _lazy("Please verify your email before adding images.")

    def post(self, request: AuthedHttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        # Advisory only — cheap, unlocked, and purely to skip the expensive
        # decode (full Pillow load + two WebP encodes) for a user already at
        # the cap. The locked re-check below inside transaction.atomic() is
        # the one that actually closes the concurrency race and must run
        # regardless of this short-circuit.
        if ProfileImage.objects.filter(user=request.user).count() >= MAX_PORTFOLIO_IMAGES:
            messages.error(
                request,
                _("You can show up to %(n)d images.") % {"n": MAX_PORTFOLIO_IMAGES},
            )
            return redirect("accounts:profile_edit")
        form = PortfolioImageForm(request.POST, request.FILES)
        if not form.is_valid():
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect("accounts:profile_edit")
        processed = form.cleaned_data["image"]
        with transaction.atomic():
            # Locks the user row for the duration of the check + create: two
            # overlapping uploads at 11 images must not both pass
            # check-then-create and land a 13th.
            User.objects.select_for_update().get(pk=request.user.pk)
            if ProfileImage.objects.filter(user=request.user).count() >= MAX_PORTFOLIO_IMAGES:
                messages.error(
                    request,
                    _("You can show up to %(n)d images.") % {"n": MAX_PORTFOLIO_IMAGES},
                )
                return redirect("accounts:profile_edit")
            ProfileImage.objects.create(
                user=request.user,
                image=processed.image,
                thumbnail=processed.thumbnail,
                caption=form.cleaned_data["caption"],
            )
        messages.success(request, _("Image added."))
        return redirect("accounts:profile_edit")


class PortfolioDeleteView(LoginRequiredMixin, View):
    def post(
        self, request: AuthedHttpRequest, pk: int, *args: object, **kwargs: object
    ) -> HttpResponse:
        stored = get_object_or_404(ProfileImage, pk=pk, user=request.user)
        # Both files go with the row — accounts.models.delete_profile_image_files
        # is on post_delete, so every deletion path cleans up, this one included.
        stored.delete()
        messages.success(request, _("Image removed."))
        return redirect("accounts:profile_edit")


class AccountView(LoginRequiredMixin, TemplateView):
    """Email verification, data export, account deletion. The profile fields
    moved to ProfileEditView."""

    template_name = "accounts/account.html"


class AccountDeleteView(LoginRequiredMixin, TemplateView):
    """Confirm, then hard-delete: contributions cascade, vouches emitted are
    anonymized (FK rules), and the avatar file is removed here. Portfolio
    image/thumbnail files go with their cascaded rows via the post_delete
    receiver in accounts.models (GDPR §14)."""

    template_name = "accounts/account_delete.html"

    def post(self, request: AuthedHttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        user = request.user
        # avatar is a FieldFile at runtime; the type checker sees the ImageField.
        avatar: Any = user.avatar
        if avatar:
            # A field on the row being deleted, so nothing cascades it away —
            # unlike the portfolio files, which their own rows' receiver takes.
            avatar.delete(save=False)
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
                return redirect("home")
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

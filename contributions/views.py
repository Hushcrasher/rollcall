"""Contribution CRUD. Creating a credit requires a verified email (design
non-negotiable #6); editing/deleting is restricted to the owner."""

from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import CreateView, DeleteView, FormView, TemplateView, UpdateView

from accounts.forms import SignupForm
from accounts.models import User
from accounts.registration import create_and_login
from contributions.forms import ContributionForm
from contributions.funnel import CREDIT_FIELDS, clear_draft, get_draft, set_draft
from contributions.models import Contribution
from games.igdb import IGDBClient
from games.models import Game
from search.services import search_games


class EmailVerifiedRequiredMixin(LoginRequiredMixin):
    """Bounce logged-in-but-unverified users to the verification notice."""

    request: Any  # provided by the Django CBV this is mixed into

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        user = self.request.user
        if user.is_authenticated and not user.is_email_verified:
            messages.error(request, _("Please verify your email before adding credits."))
            return redirect("accounts:verification_sent")
        return super().dispatch(request, *args, **kwargs)


class DeclareGameView(TemplateView):
    """Step 1 — turn a typed title into a chosen game.

    Open to anonymous visitors: asking for the account before any value is the
    friction this funnel exists to remove. Plain form posts, no htmx: the root
    carries only a text box, and the disambiguation happens here.
    """

    template_name = "contributions/declare_game.html"

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        game = self._picked_game(request)
        if game is not None:
            # `request.session` is added by middleware, which `ty` cannot see —
            # the same accommodation the codebase already uses elsewhere.
            draft = get_draft(request.session)  # ty: ignore[unresolved-attribute]
            draft["game"] = str(game.pk)
            set_draft(request.session, draft)  # ty: ignore[unresolved-attribute]
            return redirect("contributions:declare_details")
        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        query = self.request.POST.get("q", "") or self.request.GET.get("q", "")
        context["query"] = query
        context["games"] = search_games(query) if query.strip() else []
        return context

    @staticmethod
    def _picked_game(request: HttpRequest) -> Game | None:
        # Unauthenticated POST on a public page: `?game=abc` must re-render, not
        # 500, so the pk is filtered rather than coerced.
        pk = request.POST.get("game", "")
        return Game.objects.filter(pk=pk).first() if pk.isdigit() else None


class DeclareDetailsView(FormView):
    """Step 2 — the rest of the credit. The game is already chosen, so this
    renders ContributionForm without its game picker."""

    template_name = "contributions/declare_details.html"
    form_class = ContributionForm

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if "game" not in get_draft(request.session):  # ty: ignore[unresolved-attribute]
            return redirect("contributions:declare")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self) -> dict[str, Any]:
        return dict(get_draft(self.request.session))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["game"] = Game.objects.filter(pk=get_draft(self.request.session)["game"]).first()
        return context

    def form_valid(self, form: ContributionForm) -> HttpResponse:
        # Raw POST strings, not cleaned_data: the session serializer is JSON and
        # `date` is not JSON-serialisable. Step 3 re-validates through the same
        # form, so nothing is trusted on the way back in.
        draft = {field: self.request.POST.get(field, "") for field in CREDIT_FIELDS}
        set_draft(self.request.session, draft)
        return redirect("contributions:declare_account")


class DeclareAccountView(FormView):
    """Step 3 — create the account, then the credit.

    Signup auto-logs-in, so by the time the credit is written the FK is
    satisfiable and the verification mail carries no state at all: verifying two
    days later from a phone works, because there is a row to flip.
    """

    template_name = "contributions/declare_account.html"
    form_class = SignupForm

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        draft = get_draft(request.session)  # ty: ignore[unresolved-attribute]
        if "game" not in draft or "discipline" not in draft:
            return redirect("contributions:declare")
        if request.user.is_authenticated:  # ty: ignore[unresolved-attribute]
            # Already a member — nothing to sign up for.
            return self._save_credit(request, request.user)  # ty: ignore[unresolved-attribute]
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form: SignupForm) -> HttpResponse:
        user = create_and_login(self.request, form)
        return self._save_credit(self.request, user)

    def _save_credit(self, request: HttpRequest, user: User) -> HttpResponse:
        form = ContributionForm(get_draft(request.session))  # ty: ignore[unresolved-attribute]
        if not form.is_valid():
            # The draft stopped validating — a game deleted, say. Send them back
            # to fix it rather than dropping the credit silently.
            return redirect("contributions:declare_details")
        credit = form.save(commit=False)
        credit.user = user
        credit.status = (
            Contribution.Status.ACTIVE if user.is_email_verified else Contribution.Status.PENDING
        )
        credit.save()
        clear_draft(request.session)  # ty: ignore[unresolved-attribute]
        if credit.status == Contribution.Status.ACTIVE:
            messages.success(request, _("Credit added."))
            return redirect(str(user.get_absolute_url()))
        return redirect("accounts:verification_sent")


class _OwnerProfileRedirectMixin:
    # `request` is provided by the Django CBV this is mixed into; typed loosely
    # so `self.request.user` (added by middleware) resolves.
    request: Any

    def get_success_url(self) -> str:
        return reverse("accounts:profile", kwargs={"slug": self.request.user.slug})


class _IGDBContextMixin:
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        # super() resolves to the Django CBV this is mixed into.
        context: dict[str, Any] = super().get_context_data(**kwargs)  # ty: ignore[unresolved-attribute]
        context["igdb_enabled"] = IGDBClient().configured
        return context


class ContributionCreateView(
    EmailVerifiedRequiredMixin, _OwnerProfileRedirectMixin, _IGDBContextMixin, CreateView
):
    model = Contribution
    form_class = ContributionForm
    template_name = "contributions/contribution_form.html"

    def form_valid(self, form: ContributionForm) -> HttpResponse:
        form.instance.user = self.request.user
        messages.success(self.request, _("Credit added."))
        return super().form_valid(form)


class ContributionUpdateView(
    LoginRequiredMixin, _OwnerProfileRedirectMixin, _IGDBContextMixin, UpdateView
):
    model = Contribution
    form_class = ContributionForm
    template_name = "contributions/contribution_form.html"

    def get_queryset(self) -> QuerySet[Contribution]:
        return Contribution.objects.filter(user=self.request.user)  # owner-only

    def form_valid(self, form: ContributionForm) -> HttpResponse:
        messages.success(self.request, _("Credit updated."))
        return super().form_valid(form)


class ContributionDeleteView(LoginRequiredMixin, _OwnerProfileRedirectMixin, DeleteView):
    model = Contribution
    template_name = "contributions/contribution_confirm_delete.html"

    def get_queryset(self) -> QuerySet[Contribution]:
        return Contribution.objects.filter(user=self.request.user)  # owner-only

    def form_valid(self, form: Any) -> HttpResponse:
        messages.success(self.request, _("Credit deleted."))
        return super().form_valid(form)

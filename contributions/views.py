"""Contribution CRUD, and the declare funnel's three steps.

`/credits/new/` still requires a verified email (design non-negotiable #6);
editing/deleting is restricted to the owner. The declare funnel below
(`DeclareGameView` / `DeclareDetailsView` / `DeclareAccountView`) is a second,
narrower path into the same table: it writes a credit at signup regardless of
verification, `pending` until `accounts.views.verify_email` publishes it — see
docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md."""

from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.views.generic import CreateView, DeleteView, FormView, TemplateView, UpdateView
from django_ratelimit.core import is_ratelimited
from django_ratelimit.exceptions import Ratelimited

from accounts.forms import SignupForm
from accounts.mixins import EmailVerifiedRequiredMixin
from accounts.models import User
from accounts.registration import create_and_login
from contributions.forms import ContributionForm
from contributions.funnel import CREDIT_FIELDS, clear_draft, get_draft, set_draft
from contributions.models import Contribution
from games.igdb import IGDBClient, IGDBError, import_igdb_game, quota_exceeded, search_options
from games.models import Game
from search.services import search_games

# Named explicitly, like search.views.PeopleSearchView's _RATELIMIT_GROUP:
# django-ratelimit derives an unnamed decorator's group from the view's module
# and qualname, so renaming this view would silently move the counter.
_DECLARE_GAME_RATELIMIT_GROUP = "declare_game_search"

# Postgres bigint — the widest id this schema holds — is 19 digits.
_MAX_ID_DIGITS = 19


def _is_row_id(raw: str) -> bool:
    """True for a posted value safe to coerce with `int()` or filter a pk on.

    Both halves guard a 500 on a page anonymous traffic posts to:

    - `isdecimal()`, not `isdigit()`: "²" is a digit but `int()` rejects it.
      `isdecimal()` is still True for "１"/"٣", which `int()` accepts.
    - the length, because the alphabet alone does not bound it: CPython >= 3.11
      refuses `int()` on a decimal string past 4300 digits, and Django's own
      coercion raises the same on a `filter(pk=…)`. `POST /declare/` with a
      5000-digit `igdb` or `game` was an unhandled `ValueError`.
    """
    return raw.isdecimal() and len(raw) <= _MAX_ID_DIGITS


class DeclareGameView(TemplateView):
    """Step 1 — turn a typed title into a chosen game.

    Open to anonymous visitors: asking for the account before any value is the
    friction this funnel exists to remove. Plain form posts, no htmx: the root
    carries only a text box, and the disambiguation happens here.

    The trigram search this runs is an unmetered anonymous search over `Game`
    unless rate-limited. Metered by hand in `_meter_search_if_any`, called from
    both `get()` and `post()`, like `search.views.PeopleSearchView.get()`: only
    a request that actually searches (a non-blank `q`, GET or POST) spends
    quota, on one shared counter regardless of method — a bare GET always
    answers, and so does the POST that merely picks an already-listed game
    (carries `game`) — PeopleSearchView's model is "only a real search spends
    quota", and a pick isn't one. `method` is deliberately left at its default
    (`ALL`, matching every HTTP method) on the `is_ratelimited` call below —
    passing e.g. `method="POST"` would fold the method into the cache key
    (django_ratelimit.core._make_cache_key) and split GET and POST onto
    separate counters, defeating the point of sharing one.
    """

    template_name = "contributions/declare_game.html"

    # Set on the instance by the IGDB paths below. Django builds one view
    # instance per request, so this class default is never shared.
    igdb_error: str = ""

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self._meter_search_if_any(request)
        return super().get(request, *args, **kwargs)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        game = self._picked_game(request)
        if game is None and request.POST.get("igdb"):
            game = self._import_picked_igdb_game(request)
        if game is not None:
            # `request.session` is added by middleware, which `ty` cannot see —
            # the same accommodation the codebase already uses elsewhere.
            draft = get_draft(request.session)  # ty: ignore[unresolved-attribute]
            if draft.get("game") != str(game.pk):
                # A different game invalidates only the employer — the
                # funnel's JS can only SET a company, never clear one, so a
                # stale employer from the previous game would otherwise be
                # unclearable through the UI and get saved silently.
                # `discipline`, `job_title`, `start_date` and `end_date` are
                # game-independent, so a different pick leaves them alone.
                # Re-picking the SAME game (step 2's "Wrong game?" link)
                # leaves the whole draft alone so nothing typed is lost.
                draft.pop("company", None)
            draft["game"] = str(game.pk)
            set_draft(request.session, draft)  # ty: ignore[unresolved-attribute]
            return redirect("contributions:declare_details")
        self._meter_search_if_any(request)
        return self.render_to_response(self.get_context_data(**kwargs))

    @staticmethod
    def _meter_search_if_any(request: HttpRequest) -> None:
        # GET carries `q` on a direct `/declare/?q=…` hit; POST carries it from
        # the step-1 search box. Whichever it is, only a query that would
        # actually reach `search_games` (get_context_data below skips it for a
        # blank one) spends quota — the earlier version only ever checked
        # `request.POST`, so `GET /declare/?q=…` ran the trigram search over
        # the whole `Game` table for free.
        query = request.POST.get("q", "") or request.GET.get("q", "")
        if query.strip() and is_ratelimited(
            request=request,
            group=_DECLARE_GAME_RATELIMIT_GROUP,
            key="ip",
            rate=settings.SEARCH_RATELIMIT,
            increment=True,
        ):
            raise Ratelimited

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        query = self.request.POST.get("q", "") or self.request.GET.get("q", "")
        context["query"] = query
        games = search_games(query) if query.strip() else []
        context["games"] = games
        # IGDB only on a local miss, and only as an offer: everything that can
        # stop it — unconfigured, over quota, IGDB down — leaves the page as it
        # was before this existed (the miss plus the signup line). It is never
        # an error page (spec 2026-08-22-igdb-auto-fallback §4).
        if query.strip() and not games:
            self._offer_igdb_matches(context, query)
        if self.igdb_error:
            # An explicit failure from the import path wins over anything the
            # offer above may have set.
            context["igdb_error"] = self.igdb_error
        return context

    def _offer_igdb_matches(self, context: dict[str, Any], query: str) -> None:
        if not IGDBClient().configured:
            return
        try:
            options = search_options(self.request, query)
        except IGDBError:
            context["igdb_error"] = "unavailable"
            return
        # None is "over quota" — say nothing and let the signup line carry the
        # page, exactly as it did before.
        if options:
            context["igdb_options"] = options

    def _import_picked_igdb_game(self, request: HttpRequest) -> Game | None:
        """Import the IGDB game the visitor picked, then behave like a local pick.

        This is the funnel's one anonymous write path, and it amends the rule
        in spec 2026-08-11 that kept these endpoints login-gated. What it can
        cause is one row in the *games catalogue*, written from IGDB's own
        data — no user data, through the seed's idempotent upsert keyed on
        `igdb_id` (so a repeat is an update, not a duplicate), marked
        `source='igdb_live'`, and metered on the same IGDB quota as the search
        that produced the option. `igdb_import` and `company_create` stay
        `@login_required`.
        """
        raw = request.POST.get("igdb", "")
        # Junk re-renders rather than 500s — see _is_row_id for what "junk" has
        # to cover on an endpoint anonymous traffic posts to.
        if not _is_row_id(raw):
            return None
        if not IGDBClient().configured:
            # The guard _offer_igdb_matches and games.views.igdb_search already
            # carry. Without it, a deployment that never enabled IGDB still
            # drives an outbound Twitch token request from an anonymous POST and
            # can hold a worker for the full 10s import timeout. Spec §4: that
            # deployment shows the signup line and nothing else.
            return None
        if quota_exceeded(request):
            # Deliberately no igdb_error: spec §4 gives "throttled" no copy on
            # this page, and setting it here would only clobber the
            # "unavailable" that _offer_igdb_matches may legitimately set on the
            # re-render.
            #
            # Known cost, not fixed here: a failed import with a cold search
            # cache spends the quota twice in one request — once on this line,
            # once inside search_options when get_context_data rebuilds the
            # option list. Both are real IGDB calls, so neither check is wrong;
            # collapsing them would mean threading per-request state through
            # search_options, which games.views.igdb_search shares.
            return None
        try:
            game = import_igdb_game(int(raw))
        except IGDBError:
            self.igdb_error = "unavailable"
            return None
        except IntegrityError:
            # A double-click on the funnel's conversion button. Two simultaneous
            # imports of an igdb_id nobody holds yet both preload an empty
            # by-igdb_id map in games/seed/upsert.py and both bulk_create, so the
            # unique index on Game.igdb_id turns the loser into an IntegrityError
            # -> 500. Recovered here rather than in the seed, whose dedup is a
            # non-negotiable test zone (docs/02 §7): the winner has written the
            # very row this request wanted, so re-read it and carry on.
            game = Game.objects.filter(igdb_id=int(raw)).first()
        if game is None:
            self.igdb_error = "gone"
        return game

    @staticmethod
    def _picked_game(request: HttpRequest) -> Game | None:
        # Unauthenticated POST on a public page: `?game=abc` must re-render, not
        # 500, so the pk is guarded and filtered rather than coerced.
        pk = request.POST.get("game", "")
        return Game.objects.filter(pk=pk).first() if _is_row_id(pk) else None


class DeclareDetailsView(FormView):
    """Step 2 — the rest of the credit. The game is already chosen, so this
    renders ContributionForm without its game picker."""

    template_name = "contributions/declare_details.html"
    form_class = ContributionForm

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        game_pk = get_draft(request.session).get("game")  # ty: ignore[unresolved-attribute]
        if not game_pk or not Game.objects.filter(pk=game_pk).exists():
            # No game in the draft (step 1 never reached), or the game was
            # deleted between steps 1 and 2 — either way there is nothing here
            # to fill in, and rendering it would show "On ." and feed a broken
            # /games//employers/ URL to the JS.
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
        # form, so nothing is trusted on the way back in. `game` specifically
        # is taken from the session draft, not POST: the dispatch guard above
        # says "the game is fixed by step 1", and trusting a posted `game`
        # here would let a crafted POST swap it.
        draft = {field: self.request.POST.get(field, "") for field in CREDIT_FIELDS}
        draft["game"] = get_draft(self.request.session)["game"]
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
        if "game" not in draft:
            return redirect("contributions:declare")
        if "discipline" not in draft:
            # A game was picked but step 2 was never finished — send them
            # there to fill it in rather than making them re-pick the game the
            # session already holds.
            return redirect("contributions:declare_details")
        if request.user.is_authenticated and request.method in (  # ty: ignore[unresolved-attribute]
            "GET",
            "POST",
        ):
            # Already a member — nothing to sign up for. Narrowed to GET and
            # POST: GET because a member simply landing here — e.g. via
            # `?next=` after logging in — legitimately has nothing left to
            # sign up for, POST for symmetry with the anonymous path below.
            # Everything else falls through to the default dispatch instead
            # of writing — including HEAD, which browsers issue for
            # prefetch/prerender: that still answers 200 (Django aliases
            # `self.head` to `self.get` whenever `get` is defined), it just
            # never reaches this branch, so the write never happens.
            #
            # The GET branch writes to the database with no CSRF token
            # covering it — CsrfViewMiddleware runs ahead of every view
            # regardless of method, so this is not a bypass of CSRF
            # protection; a POST here without a token 403s like anywhere
            # else. What actually makes the uncovered GET tolerable is that
            # there is nothing for a forged one to control: steps 1 and 2
            # (`DeclareGameView.post`, `DeclareDetailsView.form_valid`) are
            # themselves CSRF-protected POSTs, so an attacker cannot seed the
            # victim's session draft — a forged hit on this GET can only
            # re-save whatever the victim already typed.
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
    # Lazy: a class attribute evaluates at import time, and plain gettext()
    # would bake in whatever language happened to be active then
    # (accounts/mixins.py's base class attribute is lazy for the same reason).
    verification_message = _lazy("Please verify your email before adding credits.")

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

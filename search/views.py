"""Public search page + autocomplete endpoints (htmx).

Search is open to all. There is no exhaustive "all people" listing — an empty
query returns nothing (anti-scraping posture, docs/02-ARCHITECTURE.md §5).
"""

from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.generic import TemplateView
from django_ratelimit.decorators import ratelimit

from accounts.models import User
from games.igdb import IGDBClient
from games.models import Game
from search.forms import RecruiterSearchForm
from search.services import recruiter_search, search_companies, search_games, search_people


def _search_rate(group: str, request: HttpRequest) -> str:
    return settings.SEARCH_RATELIMIT


@method_decorator(ratelimit(key="ip", rate=_search_rate, method="GET", block=True), name="get")
class SearchView(TemplateView):
    template_name = "search/search.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get("q", "")
        context["query"] = query
        context["people"] = search_people(query)
        context["games"] = search_games(query, limit=20)
        context["companies"] = search_companies(query, limit=20)
        return context


class RecruitersLandingView(TemplateView):
    """Public promise page. Honest, real counts — no inflated counters."""

    template_name = "search/recruiters_landing.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["public_profiles"] = User.objects.filter(profile_public=True).count()
        context["games"] = Game.objects.count()
        return context


class RecruiterRequiredMixin(LoginRequiredMixin):
    """Recruiter-only. Non-recruiters are funnelled to the application page."""

    request: Any

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        user = self.request.user
        if user.is_authenticated and not user.is_recruiter:
            messages.info(request, _("A recruiter account is required — apply below."))
            return redirect("accounts:recruiter_apply")
        return super().dispatch(request, *args, **kwargs)


class RecruiterSearchView(RecruiterRequiredMixin, TemplateView):
    template_name = "search/recruiter_search.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        form = RecruiterSearchForm(self.request.GET or None)
        context["form"] = form
        if self.request.GET and form.is_valid():
            cleaned = form.cleaned_data
            context["results_page"] = recruiter_search(
                discipline_id=cleaned["discipline"].pk if cleaned.get("discipline") else None,
                engine_ids=[engine.pk for engine in cleaned.get("engines") or []],
                genre_ids=[genre.pk for genre in cleaned.get("genres") or []],
                countries=list(cleaned.get("countries") or []),
                min_rating=cleaned.get("min_rating"),
                year_from=cleaned.get("year_from"),
                open_to_work=cleaned.get("open_to_work") or None,
                # Raw string, uncoerced: get_page() turns junk into page 1.
                # int() here would 500 on ?page=abc — on a public page.
                page=self.request.GET.get("page"),
            )
            context["searched"] = True
        return context


def suggest(request: HttpRequest) -> HttpResponse:
    """Nav live-search dropdown — top games + public people, as you type."""
    query = request.GET.get("q", "")
    return render(
        request,
        "search/_suggest.html",
        {
            "query": query,
            "games": search_games(query, limit=5),
            "people": search_people(query, limit=5),
            "companies": search_companies(query, limit=5),
        },
    )


def game_autocomplete(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    return render(
        request,
        "search/_game_options.html",
        {
            "games": search_games(query),
            "query": query,
            # Inline IGDB fallback option — only when IGDB is configured.
            "igdb_enabled": IGDBClient().configured,
        },
    )


def company_autocomplete(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    return render(
        request,
        "search/_company_options.html",
        {"companies": search_companies(query), "query": query},
    )

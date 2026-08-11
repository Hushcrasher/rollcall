"""Public search page + autocomplete endpoints (htmx).

Search is open to all. There is no exhaustive "all people" listing — an empty
query returns nothing (anti-scraping posture, docs/02-ARCHITECTURE.md §5).
"""

from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView
from django_countries import countries
from django_ratelimit.core import is_ratelimited
from django_ratelimit.decorators import ratelimit
from django_ratelimit.exceptions import Ratelimited

from games.igdb import IGDBClient
from games.models import Engine, Genre
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


# Named explicitly: django-ratelimit derives a decorator's group from the view's
# module and qualname, so renaming the view would have silently moved the
# counter. Distinct from SearchView's, which is the behavior today.
_RATELIMIT_GROUP = "people_search"


class PeopleSearchView(TemplateView):
    """The home page: find people by what they've worked on. Open to everyone —
    the platform is free, and showing workers that the recruiter-side tool
    exists is part of the promise (spec 2026-07-16).
    Anti-scraping: the IP rate limit in `get()` below, pagination, and
    `profile_public`. The rate limit only meters requests that carry a query
    string — the bare front door is unmetered by design, so it is not a limit
    on the view as a whole. The form's >=1-filter rule is a UX guard only, not
    a boundary."""

    template_name = "search/people_search.html"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Only a real search spends quota. This view is the home page now, so a
        # blanket limit would let one shared IP turn the front door into a 403.
        # Any query string counts — `?page=2` and junk params are part of the
        # same generated URL space, and that space is what needs metering.
        if request.GET and is_ratelimited(
            request=request,
            group=_RATELIMIT_GROUP,
            key="ip",
            rate=settings.SEARCH_RATELIMIT,
            method="GET",
            increment=True,
        ):
            # Raised directly rather than routed through
            # `settings.RATELIMIT_EXCEPTION_CLASS` (which the `@ratelimit`
            # decorator on SearchView above does honour) — a divergence, but an
            # inert one while that setting is unset: `Ratelimited` subclasses
            # `PermissionDenied`, so both paths 403 today. Set that setting and
            # this branch would stop following it.
            raise Ratelimited
        return super().get(request, *args, **kwargs)

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


# --- Recruiter-filter typeahead ---------------------------------------------
#
# These three back the engines/genres/countries filters on the people search
# (the home page), so unlike the pickers above (which sit behind a login on
# the credit form) they carry the same IP rate limit as the search pages.

_FILTER_OPTIONS_SHOWN = 10


def _reference_options(model: type[Engine] | type[Genre], query: str) -> list[tuple[Any, str]]:
    """Name lookup over a small reference table (Engine/Genre).

    A plain icontains, not `search/services.py`'s trigram matching: these are
    closed vocabularies the user is picking *from*, so a typo should show no
    match rather than guess one — and typing less shows more.
    """
    stripped = query.strip()
    if not stripped:
        return []
    rows = model.objects.filter(name__icontains=stripped)[:_FILTER_OPTIONS_SHOWN]
    return [(row.pk, row.name) for row in rows]


@ratelimit(key="ip", rate=_search_rate, method="GET", block=True)
def engine_autocomplete(request: HttpRequest) -> HttpResponse:
    options = _reference_options(Engine, request.GET.get("q", ""))
    return render(request, "search/_filter_options.html", {"options": options})


@ratelimit(key="ip", rate=_search_rate, method="GET", block=True)
def genre_autocomplete(request: HttpRequest) -> HttpResponse:
    options = _reference_options(Genre, request.GET.get("q", ""))
    return render(request, "search/_filter_options.html", {"options": options})


@ratelimit(key="ip", rate=_search_rate, method="GET", block=True)
def country_autocomplete(request: HttpRequest) -> HttpResponse:
    """Matches the country name *as translated into the active language* —
    "allem" finds Allemagne under `fr`. django-countries keeps the list in
    memory, so this touches no database.
    """
    stripped = request.GET.get("q", "").strip()
    options: list[tuple[Any, str]] = []
    if stripped:
        needle = stripped.casefold()
        options = [(code, str(name)) for code, name in countries if needle in str(name).casefold()][
            :_FILTER_OPTIONS_SHOWN
        ]
    return render(request, "search/_filter_options.html", {"options": options})

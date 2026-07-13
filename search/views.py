"""Public search page + autocomplete endpoints (htmx).

Search is open to all. There is no exhaustive "all people" listing — an empty
query returns nothing (anti-scraping posture, docs/02-ARCHITECTURE.md §5).
"""

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.generic import TemplateView

from search.services import search_companies, search_games, search_people


class SearchView(TemplateView):
    template_name = "search/search.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get("q", "")
        context["query"] = query
        context["people"] = search_people(query)
        context["games"] = search_games(query, limit=20)
        return context


def game_autocomplete(request: HttpRequest) -> HttpResponse:
    games = search_games(request.GET.get("q", ""))
    return render(request, "search/_game_options.html", {"games": games})


def company_autocomplete(request: HttpRequest) -> HttpResponse:
    companies = search_companies(request.GET.get("q", ""))
    return render(request, "search/_company_options.html", {"companies": companies})

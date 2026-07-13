"""Autocomplete endpoints (htmx) — return HTML fragments of matching options.

Reused by the contribution form (Phase 4) and simple search (Phase 5).
"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from search.services import search_companies, search_games


def game_autocomplete(request: HttpRequest) -> HttpResponse:
    games = search_games(request.GET.get("q", ""))
    return render(request, "search/_game_options.html", {"games": games})


def company_autocomplete(request: HttpRequest) -> HttpResponse:
    companies = search_companies(request.GET.get("q", ""))
    return render(request, "search/_company_options.html", {"companies": companies})

"""Game and company pages — aggregations over IGDB facts and contributions.

The game page lists contributors (contributions read game-first); the company
page aggregates games (from IGDB `game_companies`) and contributors (from
contributions whose employer is this company). Only active contributions show.
"""

from typing import Any

from django.views.generic import DetailView

from contributions.models import Contribution
from games.models import Company, Game, GameCompany


class GameDetailView(DetailView):
    model = Game
    template_name = "games/game_detail.html"
    context_object_name = "game"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["contributions"] = (
            Contribution.objects.filter(game=self.object, status=Contribution.Status.ACTIVE)
            .select_related("user", "company", "discipline")
            .order_by("discipline__sort_order", "-start_date")
        )
        context["company_links"] = GameCompany.objects.filter(game=self.object).select_related(
            "company"
        )
        return context


class CompanyDetailView(DetailView):
    model = Company
    template_name = "games/company_detail.html"
    context_object_name = "company"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["game_links"] = GameCompany.objects.filter(company=self.object).select_related(
            "game"
        )
        context["contributions"] = (
            Contribution.objects.filter(company=self.object, status=Contribution.Status.ACTIVE)
            .select_related("user", "game", "discipline")
            .order_by("-start_date")
        )
        return context

"""Game and company pages + the IGDB live-fallback endpoints.

The game page lists contributors (contributions read game-first); the company
page aggregates games (from IGDB `game_companies`) and contributors. The IGDB
endpoints let a member pull in a game missing from the seed (docs §3.1).
"""

from datetime import UTC, datetime
from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST
from django.views.generic import DetailView

from cards.data import card_url, game_card
from contributions.models import Contribution
from games.igdb import IGDBClient, IGDBError, import_igdb_game
from games.models import Company, Game, GameCompany


class GameDetailView(DetailView):
    model = Game
    template_name = "games/game_detail.html"
    context_object_name = "game"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["contributions"] = (
            # profile_public=False makes the member invisible everywhere (docs/01
            # §3.4) — this page included, or flipping the switch would still leave
            # their name on every game they shipped. Same predicate as search.
            Contribution.objects.filter(
                game=self.object,
                status=Contribution.Status.ACTIVE,
                user__profile_public=True,
            )
            .select_related("user", "company", "discipline")
            .order_by("discipline__sort_order", "-start_date")
        )
        context["company_links"] = GameCompany.objects.filter(game=self.object).select_related(
            "company"
        )
        card = game_card(self.object)
        year = f" ({self.object.release_date.year})" if self.object.release_date else ""
        context["og_title"] = f"{self.object.title}{year} · Rollcall"
        context["og_url"] = self.request.build_absolute_uri(self.object.get_absolute_url())
        context["og_image"] = card_url(self.request, "cards:game", card, self.object.slug)
        context["meta_description"] = card.stats
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
            # profile_public=False makes the member invisible everywhere (docs/01
            # §3.4) — this page included, or flipping the switch would still leave
            # their name on every company they shipped. Same predicate as search.
            Contribution.objects.filter(
                company=self.object,
                status=Contribution.Status.ACTIVE,
                user__profile_public=True,
            )
            .select_related("user", "game", "discipline")
            .order_by("-start_date")
        )
        return context


def _igdb_label(result: dict[str, Any]) -> str:
    name = result.get("name", "")
    timestamp = result.get("first_release_date")
    if timestamp:
        return f"{name} ({datetime.fromtimestamp(timestamp, tz=UTC).year})"
    return name


@login_required
def igdb_search(request: HttpRequest) -> HttpResponse:
    """htmx fragment: search IGDB live for games missing from the seed."""
    client = IGDBClient()
    context: dict[str, Any] = {}
    query = request.GET.get("q", "").strip()
    if not client.configured:
        context["error"] = "unconfigured"
    elif query:
        try:
            context["options"] = [
                {"igdb_id": r["id"], "label": _igdb_label(r)} for r in client.search_games(query)
            ]
        except IGDBError:
            context["error"] = "unavailable"
    return render(request, "games/_igdb_options.html", context)


# Quick-pick relevance order — NOT the enum strings' alphabetical order, which
# would sort porting before publisher.
_EMPLOYER_ROLE_ORDER = [
    GameCompany.Role.DEVELOPER,
    GameCompany.Role.PUBLISHER,
    GameCompany.Role.PORTING,
    GameCompany.Role.SUPPORTING,
]


def game_employers(request: HttpRequest, pk: int) -> HttpResponse:
    """The companies credited on this game — quick-picks for the employer field.
    Deduplicated across roles; ordered developer → publisher → porting → support."""
    game = get_object_or_404(Game, pk=pk)
    employers: list[dict[str, Any]] = []
    seen: set[int] = set()
    links = sorted(
        GameCompany.objects.filter(game=game).select_related("company"),
        key=lambda link: _EMPLOYER_ROLE_ORDER.index(link.role),
    )
    for link in links:
        if link.company_id in seen:
            continue
        seen.add(link.company_id)
        employers.append(
            {"id": link.company.pk, "name": link.company.name, "role": link.get_role_display()}
        )
    return render(request, "games/_employer_options.html", {"employers": employers})


@require_POST
@login_required
def company_create(request: HttpRequest) -> JsonResponse:
    """Create (or reuse) a company by name — for employers not in IGDB
    (outsourcing studios etc.). Marked source=manual."""
    name = request.POST.get("name", "").strip()
    if not name:
        return JsonResponse({"error": "name required"}, status=400)
    # `_meta` is Django model machinery the type checker cannot see — the
    # same accommodation the codebase uses for other descriptors.
    max_length = Company._meta.get_field("name").max_length or 300  # ty: ignore[unresolved-attribute]
    if len(name) > max_length:
        # varchar(300): an unchecked longer value would be a DataError 500.
        return JsonResponse({"error": "name too long"}, status=400)
    company, _ = Company.objects.get_or_create(
        name=name, defaults={"source": Company.Source.MANUAL}
    )
    return JsonResponse({"id": company.pk, "label": company.name})


@require_POST
@login_required
def igdb_import(request: HttpRequest) -> JsonResponse:
    """Import one IGDB game locally and return {id, label} for the form to select."""
    try:
        igdb_id = int(request.POST.get("igdb_id", ""))
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid id"}, status=400)
    try:
        game = import_igdb_game(igdb_id)
    except IGDBError:
        return JsonResponse({"error": "IGDB is unavailable"}, status=502)
    if game is None:
        return JsonResponse({"error": "not found"}, status=404)
    return JsonResponse({"id": game.pk, "label": game.title})

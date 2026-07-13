"""Search services — typo-tolerant trigram search over games and companies.

Isolated in the `search` module so a dedicated engine could replace Postgres
FTS later without touching callers (docs/02-ARCHITECTURE.md §2.3).
"""

import pytest

from games.models import Company, Game
from search.services import search_companies, search_games

pytestmark = pytest.mark.django_db


def test_search_games_tolerates_typos() -> None:
    Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    Game.objects.create(title="Celeste", source=Game.Source.MANUAL)

    results = list(search_games("hade"))

    assert [g.title for g in results] == ["Hades"]


def test_search_games_matches_prefixes() -> None:
    Game.objects.create(title="Celeste", source=Game.Source.MANUAL)
    Game.objects.create(title="Hades", source=Game.Source.MANUAL)

    titles = [g.title for g in search_games("cel")]

    assert "Celeste" in titles


def test_search_games_respects_limit() -> None:
    for i in range(5):
        Game.objects.create(title=f"Dungeon {i}", source=Game.Source.MANUAL)

    assert len(list(search_games("dungeon", limit=3))) == 3


def test_blank_query_returns_nothing() -> None:
    Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    assert list(search_games("   ")) == []


def test_search_companies_tolerates_typos() -> None:
    Company.objects.create(name="Supergiant Games", source=Company.Source.MANUAL)
    Company.objects.create(name="Extremely OK Games", source=Company.Source.MANUAL)

    results = list(search_companies("supergaint"))  # transposed letters

    assert results[0].name == "Supergiant Games"

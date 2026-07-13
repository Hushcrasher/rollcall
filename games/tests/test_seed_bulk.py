"""Bulk-loader edge cases — multi-chunk, slug collisions, manual-company safety."""

from dataclasses import replace
from typing import Any

import pytest

from games.models import Company, Game
from games.seed.schema import CanonicalGame
from games.seed.upsert import upsert_games

_BASE = CanonicalGame(
    igdb_id=None,
    steam_appid=None,
    title="A Game",
    release_date=None,
    summary="",
    cover_url="",
    igdb_rating=None,
    igdb_aggregated_rating=None,
    steam_positive_pct=None,
    steam_review_count=None,
)


def _c(**overrides: Any) -> CanonicalGame:
    return replace(_BASE, **overrides)


pytestmark = pytest.mark.django_db


def test_load_across_multiple_chunks() -> None:
    games = [_c(igdb_id=i, title=f"Game {i}") for i in range(1, 51)]
    stats = upsert_games(games, batch_size=10)  # 5 chunks
    assert stats == {"created": 50, "updated": 0}
    assert Game.objects.count() == 50


def test_same_title_across_the_batch_gets_unique_slugs() -> None:
    games = [_c(igdb_id=i, title="Hades") for i in range(1, 6)]
    upsert_games(games, batch_size=2)  # collisions span chunks too

    slugs = set(Game.objects.values_list("slug", flat=True))
    assert len(slugs) == 5  # all unique
    assert "hades" in slugs
    assert "hades-2" in slugs


def test_existing_manual_company_is_not_overwritten() -> None:
    """A user-created company keeps source=manual even if the seed credits it."""
    manual = Company.objects.create(name="Indie Studio", source=Company.Source.MANUAL)

    upsert_games([_c(igdb_id=1, title="G", developers=["Indie Studio"])])

    manual.refresh_from_db()
    assert manual.source == Company.Source.MANUAL  # unchanged
    assert Company.objects.filter(name="Indie Studio").count() == 1  # reused, not duplicated


def test_reference_rows_are_reused_across_chunks() -> None:
    games = [
        _c(igdb_id=i, title=f"G{i}", genres=["Action"], engines=["Unity"]) for i in range(1, 21)
    ]
    upsert_games(games, batch_size=5)
    from games.models import Engine, Genre

    assert Genre.objects.filter(name="Action").count() == 1  # created once, reused
    assert Engine.objects.filter(name="Unity").count() == 1

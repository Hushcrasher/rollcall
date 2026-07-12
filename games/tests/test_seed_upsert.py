"""Seed upsert — idempotency + write-surface discipline (docs/04 §13, §7 zone).

The seed may write ONLY [source] columns + source/last_synced_at and the
seed-owned link tables. It must never touch platform-owned data (slugs,
contributions) and must never delete a locally-known game.
"""

from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Company, Game, GameCompany, GameGenre
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


def _canonical(**overrides: Any) -> CanonicalGame:
    return replace(_BASE, **overrides)


pytestmark = pytest.mark.django_db


def test_new_igdb_game_is_created_with_source_provenance() -> None:
    upsert_games([_canonical(igdb_id=1, title="Hades", igdb_rating=91.0)])

    game = Game.objects.get(igdb_id=1)
    assert game.title == "Hades"
    assert game.igdb_rating == 91.0
    assert game.source == Game.Source.SEED
    assert game.last_synced_at is not None
    assert game.slug == "hades"


def test_steam_only_game_upserts_by_appid() -> None:
    upsert_games([_canonical(steam_appid=42, title="Indie", steam_positive_pct=95.0)])

    game = Game.objects.get(steam_appid=42)
    assert game.igdb_id is None
    assert game.steam_positive_pct == 95.0


def test_rerun_is_idempotent() -> None:
    rows = [_canonical(igdb_id=1, title="Hades")]
    upsert_games(rows)
    upsert_games(rows)  # second run

    assert Game.objects.filter(igdb_id=1).count() == 1


def test_source_columns_are_overwritten_on_refresh() -> None:
    upsert_games([_canonical(igdb_id=1, title="Old Title", igdb_rating=50.0)])
    upsert_games([_canonical(igdb_id=1, title="New Title", igdb_rating=88.0)])

    game = Game.objects.get(igdb_id=1)
    assert game.title == "New Title"
    assert game.igdb_rating == 88.0


def test_write_surface_preserves_slug_and_contributions() -> None:
    """Platform-owned data survives a refresh untouched (zero-conflict rule)."""
    upsert_games([_canonical(igdb_id=1, title="Original")])
    game = Game.objects.get(igdb_id=1)
    original_slug = game.slug

    user = User.objects.create_user(email="d@example.com", password="x", display_name="Dev")
    discipline = Discipline.objects.get(name="Programming")
    Contribution.objects.create(
        user=user, game=game, discipline=discipline, job_title="Dev", start_date=date(2020, 1, 1)
    )

    upsert_games([_canonical(igdb_id=1, title="Renamed Upstream")])

    game.refresh_from_db()
    assert game.title == "Renamed Upstream"  # source column updated
    assert game.slug == original_slug  # platform-owned, untouched
    assert Contribution.objects.filter(game=game).count() == 1  # survives


def test_upstream_deletion_never_deletes_locally() -> None:
    """A game dropped from the parquet must survive locally (it may carry credits)."""
    upsert_games([_canonical(igdb_id=1, title="Kept"), _canonical(igdb_id=2, title="Dropped")])
    # Next refresh no longer contains game 2.
    upsert_games([_canonical(igdb_id=1, title="Kept")])

    assert Game.objects.filter(igdb_id=2).exists()


def test_genres_engines_and_companies_are_linked() -> None:
    upsert_games(
        [
            _canonical(
                igdb_id=1,
                title="Big Game",
                genres=["Action", "RPG"],
                engines=["Unreal Engine"],
                developers=["Studio X"],
                publishers=["Publisher Y"],
            )
        ]
    )
    game = Game.objects.get(igdb_id=1)
    assert game.genres.count() == 2
    assert game.engines.count() == 1
    dev_link = GameCompany.objects.get(game=game, role=GameCompany.Role.DEVELOPER)
    assert dev_link.company.name == "Studio X"
    assert GameCompany.objects.filter(game=game, role=GameCompany.Role.PUBLISHER).exists()


def test_links_are_reset_to_reflect_source_on_refresh() -> None:
    upsert_games([_canonical(igdb_id=1, title="G", genres=["Action", "RPG"])])
    upsert_games([_canonical(igdb_id=1, title="G", genres=["Puzzle"])])  # genres changed upstream

    game = Game.objects.get(igdb_id=1)
    assert list(game.genres.values_list("name", flat=True)) == ["Puzzle"]
    assert GameGenre.objects.filter(game=game).count() == 1


def test_company_created_by_seed_is_marked_seed_sourced() -> None:
    upsert_games([_canonical(igdb_id=1, title="G", developers=["New Studio"])])

    company = Company.objects.get(name="New Studio")
    assert company.source == Company.Source.SEED


def test_returns_created_and_updated_counts() -> None:
    stats = upsert_games([_canonical(igdb_id=1, title="A"), _canonical(igdb_id=2, title="B")])
    assert stats == {"created": 2, "updated": 0}

    stats = upsert_games([_canonical(igdb_id=1, title="A"), _canonical(igdb_id=3, title="C")])
    assert stats == {"created": 1, "updated": 1}

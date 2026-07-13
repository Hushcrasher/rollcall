"""Upsert canonical games into Postgres with strict write-surface discipline.

Write-surface (docs/04-DATABASE-SCHEMA.md §13): the seed may write ONLY the
games `[source]` columns + `source`/`last_synced_at`, and the seed-owned link
tables (game_genres, game_engines, game_companies) + their reference rows
(genres, engines, companies). It NEVER touches platform-owned columns (slug,
parent_game_id, claimed_by, description…) and NEVER deletes a local game —
upstream deletions must not cascade to games that may carry contributions.
"""

from collections.abc import Iterable, Iterator
from itertools import islice
from typing import TypedDict

from django.db import transaction
from django.utils import timezone

from games.models import Company, Engine, Game, GameCompany, GameEngine, GameGenre, Genre
from games.seed.schema import CanonicalGame

# The exact set of game columns the seed is allowed to write.
_SOURCE_FIELDS = (
    "igdb_id",
    "steam_appid",
    "title",
    "release_date",
    "summary",
    "cover_url",
    "igdb_rating",
    "igdb_aggregated_rating",
    "steam_positive_pct",
    "steam_review_count",
    "source",
    "last_synced_at",
)


class UpsertStats(TypedDict):
    created: int
    updated: int


def _chunks(items: Iterable[CanonicalGame], size: int) -> Iterator[list[CanonicalGame]]:
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch


def _find_existing(game: CanonicalGame) -> Game | None:
    # Upsert by igdb_id when present, else by steam_appid (docs §13 upsert keys).
    if game.igdb_id is not None:
        found = Game.objects.filter(igdb_id=game.igdb_id).first()
        if found is not None:
            return found
    if game.steam_appid is not None:
        return Game.objects.filter(steam_appid=game.steam_appid).first()
    return None


def _upsert_one(game: CanonicalGame, source: str) -> bool:
    """Create or refresh a single game. Returns True if it was created."""
    source_values = {
        "igdb_id": game.igdb_id,
        "steam_appid": game.steam_appid,
        "title": game.title,
        "release_date": game.release_date,
        "summary": game.summary,
        "cover_url": game.cover_url,
        "igdb_rating": game.igdb_rating,
        "igdb_aggregated_rating": game.igdb_aggregated_rating,
        "steam_positive_pct": game.steam_positive_pct,
        "steam_review_count": game.steam_review_count,
        "source": source,
        "last_synced_at": timezone.now(),
    }

    existing = _find_existing(game)
    if existing is None:
        obj = Game(**source_values)
        obj.save()  # generates slug (platform-owned) on first insert
        created = True
    else:
        for field_name, value in source_values.items():
            setattr(existing, field_name, value)
        # update_fields lists ONLY source columns → slug and every other
        # platform-owned column are left untouched.
        existing.save(update_fields=list(_SOURCE_FIELDS))
        obj = existing
        created = False

    _sync_taxonomy(obj, Genre, GameGenre, "genre", game.genres)
    _sync_taxonomy(obj, Engine, GameEngine, "engine", game.engines)
    _sync_companies(obj, game)
    return created


def _sync_taxonomy(
    game: Game,
    reference_model: type[Genre] | type[Engine],
    link_model: type[GameGenre] | type[GameEngine],
    link_field: str,
    names: list[str],
) -> None:
    # Reset seed-owned links, then recreate from source (idempotent refresh).
    link_model.objects.filter(game=game).delete()
    for name in dict.fromkeys(names):  # de-dup, preserve order
        reference, _ = reference_model.objects.get_or_create(name=name)
        link_model.objects.create(game=game, **{link_field: reference})


def _sync_companies(game: Game, canonical: CanonicalGame) -> None:
    GameCompany.objects.filter(game=game).delete()
    role_lists = (
        (GameCompany.Role.DEVELOPER, canonical.developers),
        (GameCompany.Role.PUBLISHER, canonical.publishers),
        (GameCompany.Role.PORTING, canonical.porting),
        (GameCompany.Role.SUPPORTING, canonical.supporting),
    )
    for role, names in role_lists:
        for name in dict.fromkeys(names):
            company, _ = Company.objects.get_or_create(
                name=name, defaults={"source": Company.Source.SEED}
            )
            GameCompany.objects.get_or_create(game=game, company=company, role=role)


def upsert_games(
    games: Iterable[CanonicalGame],
    batch_size: int = 500,
    source: str = Game.Source.SEED,
) -> UpsertStats:
    """Idempotently upsert canonical games, one transaction per batch. `source`
    marks provenance (`seed` for the batch job, `igdb_live` for live fallback)."""
    stats: UpsertStats = {"created": 0, "updated": 0}
    for batch in _chunks(games, batch_size):
        with transaction.atomic():
            for game in batch:
                if _upsert_one(game, source):
                    stats["created"] += 1
                else:
                    stats["updated"] += 1
    return stats

"""Bulk-upsert canonical games into Postgres with strict write-surface discipline.

Write-surface (docs/04-DATABASE-SCHEMA.md §13): the seed may write ONLY the
games `[source]` columns + `source`/`last_synced_at`, and the seed-owned link
tables (game_genres, game_engines, game_companies) + their reference rows
(genres, engines, companies). It NEVER touches platform-owned columns (slug,
parent_game_id, claimed_by, description…) and NEVER deletes a local game —
upstream deletions must not cascade to games that may carry contributions.

Built for a ~392k cold load: reference rows are cached in memory, games and
links go in via bulk_create/bulk_update, and slugs are made unique in Python —
turning millions of per-row queries into a handful per chunk.
"""

from collections.abc import Iterable, Iterator
from itertools import islice
from typing import TypedDict

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

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
_ROLES = ("developers", "publishers", "porting", "supporting")

# IGDB payloads never carry Steam data, so an igdb_live upsert over an existing
# game must leave the Steam columns alone — writing the canonical's Nones would
# wipe seed-owned data until the next weekly refresh restores it.
_STEAM_FIELDS = ("steam_appid", "steam_positive_pct", "steam_review_count")


class UpsertStats(TypedDict):
    created: int
    updated: int


def _chunks(items: Iterable[CanonicalGame], size: int) -> Iterator[list[CanonicalGame]]:
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch


class _SlugAllocator:
    """Hands out unique slugs (title → slug), tracking every slug already used
    (in the DB and issued this run) so bulk_create never hits the unique index."""

    def __init__(self, used: set[str]) -> None:
        self._used = used
        self._next_suffix: dict[str, int] = {}

    def allocate(self, title: str) -> str:
        base = slugify(title)[:200] or "game"
        if base not in self._used:
            self._used.add(base)
            return base
        suffix = self._next_suffix.get(base, 2)
        candidate = f"{base}-{suffix}"
        while candidate in self._used:
            suffix += 1
            candidate = f"{base}-{suffix}"
        self._next_suffix[base] = suffix + 1
        self._used.add(candidate)
        return candidate


class _BulkLoader:
    def __init__(self, source: str) -> None:
        self.source = source
        self.now = timezone.now()
        self.update_fields = [
            f for f in _SOURCE_FIELDS if source != Game.Source.IGDB_LIVE or f not in _STEAM_FIELDS
        ]
        self.stats: UpsertStats = {"created": 0, "updated": 0}
        self.genres: dict[str, int] = {}
        self.engines: dict[str, int] = {}
        self.companies: dict[str, int] = {}
        self.by_igdb: dict[int, int] = {}
        self.by_steam: dict[int, int] = {}
        # Games and companies have independent unique-slug namespaces.
        self.game_slugs = _SlugAllocator(set())
        self.company_slugs = _SlugAllocator(set())

    def preload(self) -> None:
        self.genres = dict(Genre.objects.values_list("name", "pk"))
        self.engines = dict(Engine.objects.values_list("name", "pk"))
        self.companies = dict(Company.objects.values_list("name", "pk"))
        self.by_igdb = {
            i: pk for i, pk in Game.objects.values_list("igdb_id", "pk") if i is not None
        }
        self.by_steam = {
            s: pk for s, pk in Game.objects.values_list("steam_appid", "pk") if s is not None
        }
        self.game_slugs = _SlugAllocator(set(Game.objects.values_list("slug", flat=True)))
        self.company_slugs = _SlugAllocator(set(Company.objects.values_list("slug", flat=True)))

    def _ensure_refs(
        self, model: type[Genre] | type[Engine], cache: dict[str, int], names: set[str]
    ) -> None:
        missing = [n for n in names if n and n not in cache]
        if not missing:
            return
        model.objects.bulk_create([model(name=n) for n in missing], ignore_conflicts=True)
        cache.update(model.objects.filter(name__in=missing).values_list("name", "pk"))

    def _ensure_companies(self, names: set[str]) -> None:
        missing = [n for n in names if n and n not in self.companies]
        if not missing:
            return
        # Existing companies (incl. user-created source=manual) are left untouched.
        Company.objects.bulk_create(
            [
                Company(name=n, slug=self.company_slugs.allocate(n), source=Company.Source.SEED)
                for n in missing
            ],
            ignore_conflicts=True,
        )
        self.companies.update(Company.objects.filter(name__in=missing).values_list("name", "pk"))

    def _source_values(self, game: CanonicalGame) -> dict[str, object]:
        return {
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
            "source": self.source,
            "last_synced_at": self.now,
        }

    @transaction.atomic
    def process(self, chunk: list[CanonicalGame]) -> None:
        # 1. Reference rows (genres/engines/companies) new to this chunk.
        self._ensure_refs(Genre, self.genres, {n for g in chunk for n in g.genres})
        self._ensure_refs(Engine, self.engines, {n for g in chunk for n in g.engines})
        self._ensure_companies({n for g in chunk for r in _ROLES for n in getattr(g, r)})

        # 2. Split into create vs update; build Game objects.
        to_create: list[tuple[Game, CanonicalGame]] = []
        to_update: list[tuple[Game, CanonicalGame]] = []
        for game in chunk:
            values = self._source_values(game)
            pk = None
            if game.igdb_id is not None:
                pk = self.by_igdb.get(game.igdb_id)
            if pk is None and game.steam_appid is not None:
                pk = self.by_steam.get(game.steam_appid)
            if pk is None:
                to_create.append((Game(slug=self.game_slugs.allocate(game.title), **values), game))
            else:
                to_update.append((Game(pk=pk, **values), game))

        Game.objects.bulk_create([g for g, _ in to_create], batch_size=1000)
        if to_update:
            Game.objects.bulk_update(
                [g for g, _ in to_update], fields=self.update_fields, batch_size=1000
            )
        self.stats["created"] += len(to_create)
        self.stats["updated"] += len(to_update)

        # 3. Reset + recreate the seed-owned links for every game in this chunk.
        self._sync_links([g for g, _ in to_create + to_update], to_create + to_update)

    def _sync_links(self, games: list[Game], pairs: list[tuple[Game, CanonicalGame]]) -> None:
        pks = [g.pk for g in games]
        GameGenre.objects.filter(game_id__in=pks).delete()
        GameEngine.objects.filter(game_id__in=pks).delete()
        GameCompany.objects.filter(game_id__in=pks).delete()

        genre_links, engine_links, company_links = [], [], []
        for game, canonical in pairs:
            for name in dict.fromkeys(canonical.genres):
                genre_links.append(GameGenre(game_id=game.pk, genre_id=self.genres[name]))
            for name in dict.fromkeys(canonical.engines):
                engine_links.append(GameEngine(game_id=game.pk, engine_id=self.engines[name]))
            for role_field, role in (
                ("developers", GameCompany.Role.DEVELOPER),
                ("publishers", GameCompany.Role.PUBLISHER),
                ("porting", GameCompany.Role.PORTING),
                ("supporting", GameCompany.Role.SUPPORTING),
            ):
                for name in dict.fromkeys(getattr(canonical, role_field)):
                    company_links.append(
                        GameCompany(game_id=game.pk, company_id=self.companies[name], role=role)
                    )
        GameGenre.objects.bulk_create(genre_links, batch_size=2000, ignore_conflicts=True)
        GameEngine.objects.bulk_create(engine_links, batch_size=2000, ignore_conflicts=True)
        GameCompany.objects.bulk_create(company_links, batch_size=2000, ignore_conflicts=True)


def upsert_games(
    games: Iterable[CanonicalGame],
    batch_size: int = 2000,
    source: str = Game.Source.SEED,
) -> UpsertStats:
    """Idempotently bulk-upsert canonical games. `source` marks provenance
    (`seed` for the batch job, `igdb_live` for the live fallback)."""
    loader = _BulkLoader(source)
    loader.preload()
    for chunk in _chunks(games, batch_size):
        loader.process(chunk)
    return loader.stats

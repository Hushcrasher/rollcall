"""IGDB API client — live fallback for games missing from the seed.

IGDB is authenticated through Twitch OAuth (client-credentials flow). This
client fetches and caches an access token, runs apicalypse queries, and maps
IGDB game objects to the seed's `CanonicalGame` so imports reuse the same
upsert path (docs/01-DESIGN.md §3.1, `Game.source = igdb_live`).

The HTTP call is isolated in `_http` so tests can stub it — no network.
"""

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest
from django_ratelimit.core import is_ratelimited

from games.models import Game
from games.seed.schema import CanonicalGame
from games.seed.upsert import upsert_games

_TOKEN_CACHE_KEY = "igdb:access_token"
_SEARCH_CACHE_PREFIX = "igdb:search:"
_SEARCH_CACHE_TTL = 60 * 60 * 24  # the catalogue this backstops refreshes weekly
_TIMEOUT = 10
# Search now runs inside a page render (spec 2026-08-22-igdb-auto-fallback §1),
# so it must not hold a worker for _TIMEOUT. get_game keeps the long one: it is
# the import path, reached by one deliberate click.
_SEARCH_TIMEOUT = 4


class IGDBError(Exception):
    """IGDB is unreachable or returned an error."""


class IGDBClient:
    TOKEN_URL = "https://id.twitch.tv/oauth2/token"
    API_BASE = "https://api.igdb.com/v4"

    def __init__(self, client_id: str | None = None, client_secret: str | None = None) -> None:
        self.client_id = client_id if client_id is not None else settings.IGDB_CLIENT_ID
        self.client_secret = (
            client_secret if client_secret is not None else settings.IGDB_CLIENT_SECRET
        )

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def search_games(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        safe = query.replace('"', "").strip()
        body = (
            f'search "{safe}"; fields id,name,first_release_date;'
            f" where version_parent = null; limit {limit};"
        )
        return self._query("games", body, timeout=_SEARCH_TIMEOUT)

    def get_game(self, igdb_id: int) -> dict[str, Any] | None:
        body = (
            "fields id,name,first_release_date,summary,cover.url,rating,aggregated_rating,"
            "genres.name,game_engines.name,involved_companies.company.name,"
            "involved_companies.developer,involved_companies.publisher,"
            "involved_companies.porting,involved_companies.supporting;"
            f" where id = {int(igdb_id)};"
        )
        results = self._query("games", body)
        return results[0] if results else None

    def _query(self, endpoint: str, body: str, timeout: float = _TIMEOUT) -> list[dict[str, Any]]:
        token = self._get_token()
        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        result = self._http(f"{self.API_BASE}/{endpoint}", body.encode(), headers, timeout)
        return result if isinstance(result, list) else []

    def _get_token(self) -> str:
        cached = cache.get(_TOKEN_CACHE_KEY)
        if cached:
            return cached
        params = urllib.parse.urlencode(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            }
        ).encode()
        data = self._http(self.TOKEN_URL, params, {})
        token = data.get("access_token")
        if not token:
            raise IGDBError("No access_token in the Twitch OAuth response")
        cache.set(_TOKEN_CACHE_KEY, token, timeout=max(60, int(data.get("expires_in", 3600)) - 60))
        return token

    def _http(
        self, url: str, data: bytes, headers: dict[str, str], timeout: float = _TIMEOUT
    ) -> Any:
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise IGDBError(f"IGDB request failed: {exc}") from exc


def igdb_label(result: dict[str, Any]) -> str:
    """`"Celeste (2018)"` — the label both callers show for an IGDB match.

    Lives here rather than in a view: it formats an IGDB payload, not a view's
    context, and it has two callers in two apps.
    """
    name = result.get("name", "")
    timestamp = result.get("first_release_date")
    if timestamp:
        return f"{name} ({datetime.fromtimestamp(timestamp, tz=UTC).year})"
    return name


_QUOTA_GROUP = "igdb_search"


def quota_exceeded(request: HttpRequest) -> bool:
    """True when this IP has spent its IGDB allowance for the window.

    Two things make this unlike every other limit in the project, and both are
    deliberate (spec 2026-08-22-igdb-auto-fallback §2):

    - **It never blocks.** No `block=True`, no `Ratelimited`. Reaching the
      quota means the caller skips the IGDB call and falls back to the copy
      that existed before this feature — 403-ing a page whose own local
      results are perfectly good would be a worse outcome than not asking a
      third party.
    - **Only call it when a live request is about to be made.** A cache hit
      costs IGDB nothing, so it must not spend quota; callers check the cache
      first.

    RATELIMIT_FAIL_OPEN is already True project-wide, so an unreachable cache
    un-meters rather than 500s — bounded here by the 4s search timeout.
    """
    return is_ratelimited(
        request=request,
        group=_QUOTA_GROUP,
        key="ip",
        rate=settings.IGDB_RATELIMIT,
        increment=True,
    )


def _search_cache_key(query: str) -> str:
    # Normalised so two spellings of one title share an entry, and hashed
    # because an IGDB query is arbitrary user text and a cache key is not.
    # usedforsecurity=False: this is a cache key, not a digest anyone trusts —
    # without it ruff's S324 flags sha1 and CI fails.
    normalised = " ".join(query.split()).casefold()
    return (
        _SEARCH_CACHE_PREFIX + hashlib.sha1(normalised.encode(), usedforsecurity=False).hexdigest()
    )


def cached_search(
    query: str, limit: int = 10, client: IGDBClient | None = None
) -> list[dict[str, Any]]:
    """IGDB search behind a 24h cache keyed on the normalised query.

    The empty list is cached too, deliberately: a title on neither Rollcall nor
    IGDB is exactly what the next visitor will type, and suppressing that
    repeat is most of what this cache is for. Raises IGDBError like the client
    it wraps.
    """
    key = _search_cache_key(query)
    cached = cache.get(key)
    if cached is not None:
        return cached
    results = (client or IGDBClient()).search_games(query, limit=limit)
    cache.set(key, results, timeout=_SEARCH_CACHE_TTL)
    return results


def _release_date(timestamp: int | None) -> date | None:
    if not timestamp:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC).date()


def _cover_url(cover: dict[str, Any] | None) -> str:
    if not cover or not cover.get("url"):
        return ""
    # IGDB returns "//images.igdb.com/.../t_thumb/co....jpg" — upgrade to https
    # and a usable size.
    return ("https:" + cover["url"]).replace("t_thumb", "t_cover_big")


def _companies(data: dict[str, Any], flag: str) -> list[str]:
    return [
        involved["company"]["name"]
        for involved in data.get("involved_companies", [])
        if involved.get(flag) and involved.get("company", {}).get("name")
    ]


def igdb_to_canonical(data: dict[str, Any]) -> CanonicalGame:
    return CanonicalGame(
        igdb_id=data["id"],
        steam_appid=None,
        title=data["name"],
        release_date=_release_date(data.get("first_release_date")),
        summary=data.get("summary") or "",
        cover_url=_cover_url(data.get("cover")),
        igdb_rating=data.get("rating"),
        igdb_aggregated_rating=data.get("aggregated_rating"),
        steam_positive_pct=None,
        steam_review_count=None,
        genres=[g["name"] for g in data.get("genres", []) if g.get("name")],
        engines=[e["name"] for e in data.get("game_engines", []) if e.get("name")],
        developers=_companies(data, "developer"),
        publishers=_companies(data, "publisher"),
        porting=_companies(data, "porting"),
        supporting=_companies(data, "supporting"),
    )


def import_igdb_game(igdb_id: int, client: IGDBClient | None = None) -> Game | None:
    """Fetch one game from IGDB and create/refresh it locally (source=igdb_live).

    Reuses the seed's upsert path, so genres/engines/companies are linked the
    same way. Returns the local Game, or None if IGDB has no such game.
    """
    client = client or IGDBClient()
    data = client.get_game(igdb_id)
    if data is None:
        return None
    canonical = igdb_to_canonical(data)
    upsert_games([canonical], source=Game.Source.IGDB_LIVE)
    return Game.objects.filter(igdb_id=canonical.igdb_id).first()

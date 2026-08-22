"""IGDB client — query building, token caching, and IGDB→CanonicalGame mapping.

No network: the HTTP layer (`_http`) is monkeypatched with canned responses.
"""

from datetime import date
from typing import Any

import pytest
from django.core.cache import cache
from django.test import RequestFactory

from games.igdb import IGDBClient, cached_search, igdb_label, igdb_to_canonical, quota_exceeded

# A trimmed IGDB `games` response (Hades).
HADES = {
    "id": 113112,
    "name": "Hades",
    "first_release_date": 1600300800,  # 2020-09-17 UTC
    "summary": "A rogue-like dungeon crawler.",
    "cover": {"url": "//images.igdb.com/igdb/image/upload/t_thumb/co2h2f.jpg"},
    "rating": 91.5,
    "aggregated_rating": 93.0,
    "genres": [{"name": "Indie"}, {"name": "Role-playing (RPG)"}],
    "game_engines": [{"name": "In-house engine"}],
    "involved_companies": [
        {"company": {"name": "Supergiant Games"}, "developer": True, "publisher": True},
        {"company": {"name": "Private Division"}, "developer": False, "publisher": True},
    ],
}


def test_search_builds_an_apicalypse_query(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_http(
        self: IGDBClient, url: str, data: bytes, headers: dict[str, str], timeout: float = 10
    ) -> Any:
        captured["url"] = url
        captured["body"] = data.decode()
        return [{"id": 1, "name": "Hades"}]

    monkeypatch.setattr(IGDBClient, "_http", fake_http)
    monkeypatch.setattr(IGDBClient, "_get_token", lambda self: "tok")

    client = IGDBClient(client_id="cid", client_secret="secret")
    results = client.search_games("hades", limit=5)

    assert captured["url"].endswith("/games")
    assert 'search "hades";' in captured["body"]
    assert "limit 5;" in captured["body"]
    assert results[0]["name"] == "Hades"


def test_search_strips_quotes_to_avoid_query_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        IGDBClient,
        "_http",
        lambda self, url, data, headers, timeout=10: captured.setdefault("b", data.decode()),
    )
    monkeypatch.setattr(IGDBClient, "_get_token", lambda self: "tok")

    IGDBClient(client_id="c", client_secret="s").search_games('ha"des; drop')

    assert '"' not in captured["b"].split("search ", 1)[1].split(";", 1)[0].strip('"')


def test_configured_reflects_credentials() -> None:
    assert IGDBClient(client_id="c", client_secret="s").configured is True
    assert IGDBClient(client_id="", client_secret="").configured is False


def test_mapping_igdb_game_to_canonical() -> None:
    canonical = igdb_to_canonical(HADES)

    assert canonical.igdb_id == 113112
    assert canonical.steam_appid is None
    assert canonical.title == "Hades"
    assert canonical.release_date == date(2020, 9, 17)
    assert canonical.igdb_rating == 91.5
    assert canonical.igdb_aggregated_rating == 93.0
    assert sorted(canonical.genres) == ["Indie", "Role-playing (RPG)"]
    assert canonical.engines == ["In-house engine"]
    assert canonical.developers == ["Supergiant Games"]
    assert sorted(canonical.publishers) == ["Private Division", "Supergiant Games"]
    # A real https cover URL at a usable size, not the //... thumb.
    assert canonical.cover_url.startswith("https://")
    assert "t_thumb" not in canonical.cover_url


def test_mapping_tolerates_sparse_data() -> None:
    canonical = igdb_to_canonical({"id": 5, "name": "Bare Game"})
    assert canonical.title == "Bare Game"
    assert canonical.release_date is None
    assert canonical.summary == ""
    assert canonical.cover_url == ""
    assert canonical.genres == []
    assert canonical.developers == []


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    # LocMemCache is process-wide and nothing clears it between tests, so a
    # query cached by one test would silently satisfy another's assertion
    # about how many times IGDB was called.
    cache.clear()


def _counting_search(calls: list[str]) -> Any:
    def search(self: IGDBClient, query: str, limit: int = 10) -> list[dict[str, Any]]:
        calls.append(query)
        return [{"id": 40477, "name": "Slay the Spire", "first_release_date": 1548201600}]

    return search


def test_cached_search_calls_igdb_once_for_a_repeated_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(IGDBClient, "search_games", _counting_search(calls))
    assert cached_search("Slay the Spire")[0]["id"] == 40477
    assert cached_search("Slay the Spire")[0]["id"] == 40477
    assert len(calls) == 1


def test_cached_search_normalises_case_and_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two people typing the same title differently must not cost two calls."""
    calls: list[str] = []
    monkeypatch.setattr(IGDBClient, "search_games", _counting_search(calls))
    cached_search("  Slay   The Spire ")
    cached_search("slay the spire")
    assert len(calls) == 1


def test_cached_search_caches_a_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated misses are exactly the traffic worth suppressing: a title on
    neither Rollcall nor IGDB is what the next visitor types too."""
    calls: list[str] = []

    def empty(self: IGDBClient, query: str, limit: int = 10) -> list[dict[str, Any]]:
        calls.append(query)
        return []

    monkeypatch.setattr(IGDBClient, "search_games", empty)
    assert cached_search("nonexistent game") == []
    assert cached_search("nonexistent game") == []
    assert len(calls) == 1


def test_search_uses_the_short_timeout_and_get_game_keeps_the_long_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A search now runs inside a page render and must not hold a worker for
    ten seconds; the import path is one deliberate click and keeps its head
    room."""
    seen: list[float] = []

    def fake_http(
        self: IGDBClient,
        url: str,
        data: bytes,
        headers: dict[str, str],
        timeout: float = 10,
    ) -> Any:
        seen.append(timeout)
        return []

    monkeypatch.setattr(IGDBClient, "_http", fake_http)
    monkeypatch.setattr(IGDBClient, "_get_token", lambda self: "tok")
    client = IGDBClient(client_id="c", client_secret="s")
    client.search_games("x")
    client.get_game(1)
    assert seen == [4, 10]


def test_igdb_label_appends_the_release_year() -> None:
    assert igdb_label({"name": "Celeste", "first_release_date": 1516924800}) == "Celeste (2018)"
    assert igdb_label({"name": "Unreleased"}) == "Unreleased"


def test_quota_allows_up_to_the_limit_then_reports_exceeded(settings: Any) -> None:
    settings.RATELIMIT_ENABLE = True
    settings.IGDB_RATELIMIT = "1/m"
    request = RequestFactory().get("/declare/")
    assert quota_exceeded(request) is False
    assert quota_exceeded(request) is True


def test_quota_is_independent_of_the_search_ratelimit(settings: Any) -> None:
    """The local trigram search is cheap and ours; an IGDB call is a third
    party's quota. Spending one must not spend the other."""
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    settings.IGDB_RATELIMIT = "5/m"
    request = RequestFactory().get("/declare/")
    for _ in range(5):
        assert quota_exceeded(request) is False
    assert quota_exceeded(request) is True

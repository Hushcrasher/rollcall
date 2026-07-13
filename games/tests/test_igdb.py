"""IGDB client — query building, token caching, and IGDB→CanonicalGame mapping.

No network: the HTTP layer (`_http`) is monkeypatched with canned responses.
"""

from datetime import date
from typing import Any

import pytest

from games.igdb import IGDBClient, igdb_to_canonical

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

    def fake_http(self: IGDBClient, url: str, data: bytes, headers: dict[str, str]) -> Any:
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
        lambda self, url, data, headers: captured.setdefault("b", data.decode()),
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

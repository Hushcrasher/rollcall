"""prepare_seed_parquet — the Steam↔IGDB merge (non-negotiable test zone #1).

Fakes the raw source files, runs the join, and reads the prepared parquet back.
"""

from datetime import date, datetime
from pathlib import Path

from games.seed.pipeline import read_canonical_games
from games.seed.prepare import prepare_seed_parquet
from games.tests.seed_helpers import write_typed_parquet

_IGDB_COLS = [
    ("igdb_id", "BIGINT"),
    ("steam_app_id", "BIGINT"),
    ("game_name", "VARCHAR"),
    ("summary", "VARCHAR"),
    ("engine_names", "VARCHAR[]"),
    ("developer_names", "VARCHAR[]"),
    ("publisher_names", "VARCHAR[]"),
]
_HC_COLS = [
    ("app_id", "BIGINT"),
    ("name", "VARCHAR"),
    ("review_score", "DOUBLE"),
    ("reviews_steam", "BIGINT"),
    ("genres", "VARCHAR[]"),
    ("game_engines", "VARCHAR[]"),
    ("developers", "VARCHAR[]"),
    ("publishers", "VARCHAR[]"),
    ("steam_release_date", "TIMESTAMP"),
    ("about_the_game", "VARCHAR"),
]
_SD_COLS = [
    ("steam_appid", "BIGINT"),
    ("name", "VARCHAR"),
    ("header_image", "VARCHAR"),
    ("short_description", "VARCHAR"),
]
_RD_COLS = [("igdb_id", "BIGINT"), ("date", "DATE")]


def _run(tmp_path: Path, igdb: list, hc: list, sd: list, rd: list) -> list:  # noqa: ANN001
    paths = {
        "igdb": write_typed_parquet(tmp_path / "igdb.parquet", _IGDB_COLS, igdb),
        "hushcrasher": write_typed_parquet(tmp_path / "hc.parquet", _HC_COLS, hc),
        "steamdb": write_typed_parquet(tmp_path / "sd.parquet", _SD_COLS, sd),
        "release_dates": write_typed_parquet(tmp_path / "rd.parquet", _RD_COLS, rd),
    }
    out = str(tmp_path / "rollcall_games.parquet")
    prepare_seed_parquet(out_path=out, **paths)
    return read_canonical_games(out)


def test_linked_game_merges_igdb_identity_with_steam_data(tmp_path: Path) -> None:
    games = _run(
        tmp_path,
        igdb=[
            {
                "igdb_id": 113112,
                "steam_app_id": 1145360,
                "game_name": "Hades",
                "summary": "Rogue-lite.",
                "engine_names": ["Proprietary Engine"],
                "developer_names": ["Supergiant Games"],
                "publisher_names": None,
            }
        ],
        hc=[
            {
                "app_id": 1145360,
                "name": "Hades",
                "review_score": 98.0,
                "reviews_steam": 275606,
                "genres": ["Action", "RPG"],
                "game_engines": ["In-house engine"],
                "developers": ["Supergiant Games"],
                "publishers": ["Netflix"],
                "steam_release_date": datetime(2020, 9, 17),
                "about_the_game": "x",
            }
        ],
        sd=[
            {
                "steam_appid": 1145360,
                "name": "Hades",
                "header_image": "https://cdn/hades.jpg",
                "short_description": "s",
            }
        ],
        rd=[{"igdb_id": 113112, "date": date(2018, 12, 7)}],
    )

    assert len(games) == 1
    g = games[0]
    assert g.igdb_id == 113112 and g.steam_appid == 1145360
    assert g.title == "Hades"
    assert g.release_date == date(2018, 12, 7)  # earliest IGDB release
    assert g.steam_positive_pct == 98.0 and g.steam_review_count == 275606
    assert sorted(g.genres) == ["Action", "RPG"]  # genres come from Steam
    assert g.engines == ["Proprietary Engine"]  # engines prefer IGDB
    assert g.cover_url == "https://cdn/hades.jpg"
    assert g.publishers == ["Netflix"]  # IGDB empty → Steam fallback


def test_igdb_game_without_steam_is_included_with_null_rating(tmp_path: Path) -> None:
    games = _run(
        tmp_path,
        igdb=[
            {
                "igdb_id": 500,
                "steam_app_id": None,
                "game_name": "Console Exclusive",
                "summary": "s",
                "engine_names": ["RE Engine"],
                "developer_names": ["Capcom"],
                "publisher_names": ["Capcom"],
            }
        ],
        hc=[],
        sd=[],
        rd=[{"igdb_id": 500, "date": date(2022, 3, 1)}],
    )
    assert len(games) == 1
    g = games[0]
    assert g.igdb_id == 500 and g.steam_appid is None
    assert g.steam_positive_pct is None  # excluded only by a rating filter
    assert g.engines == ["RE Engine"]
    assert g.release_date == date(2022, 3, 1)


def test_steam_only_game_is_included(tmp_path: Path) -> None:
    games = _run(
        tmp_path,
        igdb=[],
        hc=[
            {
                "app_id": 999,
                "name": "Steam Indie",
                "review_score": 90.0,
                "reviews_steam": 1200,
                "genres": ["Indie"],
                "game_engines": ["Godot"],
                "developers": ["Solo Dev"],
                "publishers": None,
                "steam_release_date": datetime(2021, 5, 1),
                "about_the_game": "about",
            }
        ],
        sd=[],
        rd=[],
    )
    assert len(games) == 1
    g = games[0]
    assert g.igdb_id is None and g.steam_appid == 999
    assert g.title == "Steam Indie"
    assert g.steam_positive_pct == 90.0
    assert g.genres == ["Indie"] and g.engines == ["Godot"]


def test_total_is_all_igdb_plus_unlinked_steam(tmp_path: Path) -> None:
    games = _run(
        tmp_path,
        igdb=[
            {
                "igdb_id": 1,
                "steam_app_id": 10,
                "game_name": "Linked",
                "summary": None,
                "engine_names": None,
                "developer_names": None,
                "publisher_names": None,
            },
            {
                "igdb_id": 2,
                "steam_app_id": None,
                "game_name": "IgdbOnly",
                "summary": None,
                "engine_names": None,
                "developer_names": None,
                "publisher_names": None,
            },
        ],
        hc=[
            {
                "app_id": 10,
                "name": "Linked",
                "review_score": 80.0,
                "reviews_steam": 5,
                "genres": None,
                "game_engines": None,
                "developers": None,
                "publishers": None,
                "steam_release_date": None,
                "about_the_game": None,
            },
            {
                "app_id": 20,
                "name": "SteamOnly",
                "review_score": 70.0,
                "reviews_steam": 3,
                "genres": None,
                "game_engines": None,
                "developers": None,
                "publishers": None,
                "steam_release_date": None,
                "about_the_game": None,
            },
        ],
        sd=[],
        rd=[],
    )
    # 2 IGDB games + 1 unlinked Steam game (appid 20); appid 10 is linked.
    ids = {(g.igdb_id, g.steam_appid) for g in games}
    assert ids == {(1, 10), (2, None), (None, 20)}

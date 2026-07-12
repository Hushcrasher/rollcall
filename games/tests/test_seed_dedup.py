"""Steam↔IGDB dedup — non-negotiable test zone #1 (docs/02-ARCHITECTURE.md §7).

These tests need no database: the pipeline is pure DuckDB SQL over a parquet.
"""

from pathlib import Path

from games.seed.pipeline import read_canonical_games
from games.tests.seed_helpers import igdb_row, steam_row, write_parquet


def test_igdb_only_row_becomes_one_canonical_game(tmp_path: Path) -> None:
    path = write_parquet(
        tmp_path / "g.parquet",
        [igdb_row(igdb_id=100, title="Hades", igdb_rating=91.0)],
    )
    games = read_canonical_games(path)
    assert len(games) == 1
    game = games[0]
    assert game.igdb_id == 100
    assert game.steam_appid is None
    assert game.title == "Hades"
    assert game.igdb_rating == 91.0


def test_steam_only_row_becomes_one_canonical_game(tmp_path: Path) -> None:
    path = write_parquet(
        tmp_path / "g.parquet",
        [steam_row(steam_appid=555, title="Indie Gem", steam_positive_pct=97.0)],
    )
    games = read_canonical_games(path)
    assert len(games) == 1
    game = games[0]
    assert game.igdb_id is None
    assert game.steam_appid == 555
    assert game.title == "Indie Gem"
    assert game.steam_positive_pct == 97.0


def test_igdb_and_steam_rows_sharing_appid_merge_into_one(tmp_path: Path) -> None:
    """The heart of dedup: one real game, two source rows → a single canonical
    game with IGDB identity AND Steam review stats. No standalone steam row."""
    path = write_parquet(
        tmp_path / "g.parquet",
        [
            igdb_row(igdb_id=200, steam_appid=999, title="Celeste", igdb_rating=90.0),
            steam_row(
                steam_appid=999, title="Celeste", steam_positive_pct=98.0, steam_review_count=50000
            ),
        ],
    )
    games = read_canonical_games(path)
    assert len(games) == 1
    game = games[0]
    assert game.igdb_id == 200
    assert game.steam_appid == 999
    assert game.igdb_rating == 90.0
    assert game.steam_positive_pct == 98.0  # merged from the Steam side
    assert game.steam_review_count == 50000


def test_duplicate_igdb_id_within_parquet_is_deduped(tmp_path: Path) -> None:
    path = write_parquet(
        tmp_path / "g.parquet",
        [
            igdb_row(igdb_id=300, title="Dupe A"),
            igdb_row(igdb_id=300, title="Dupe B"),
        ],
    )
    games = read_canonical_games(path)
    assert len(games) == 1
    assert games[0].igdb_id == 300


def test_genres_engines_companies_flow_through(tmp_path: Path) -> None:
    path = write_parquet(
        tmp_path / "g.parquet",
        [
            igdb_row(
                igdb_id=400,
                title="Big Game",
                genres=["Action", "RPG"],
                engines=["Unreal Engine"],
                developers=["Studio X"],
                publishers=["Publisher Y"],
            )
        ],
    )
    game = read_canonical_games(path)[0]
    assert sorted(game.genres) == ["Action", "RPG"]
    assert game.engines == ["Unreal Engine"]
    assert game.developers == ["Studio X"]
    assert game.publishers == ["Publisher Y"]

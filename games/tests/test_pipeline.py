"""Seed pipeline — reads the prepared parquet (one row per game) into
CanonicalGames. Needs no database."""

from datetime import date
from pathlib import Path

from games.seed.pipeline import read_canonical_games
from games.tests.seed_helpers import game_row, write_prepared_parquet


def test_reads_an_igdb_game(tmp_path: Path) -> None:
    path = write_prepared_parquet(
        tmp_path / "g.parquet",
        [
            game_row(
                igdb_id=100,
                steam_appid=1145360,
                title="Hades",
                release_date=date(2020, 9, 17),
                steam_positive_pct=98.0,
                steam_review_count=275606,
                genres=["Action", "RPG"],
                engines=["Proprietary Engine"],
                developers=["Supergiant Games"],
                publishers=["Netflix", "Supergiant Games"],
            )
        ],
    )
    games = read_canonical_games(path)
    assert len(games) == 1
    game = games[0]
    assert game.igdb_id == 100
    assert game.steam_appid == 1145360
    assert game.title == "Hades"
    assert game.release_date == date(2020, 9, 17)
    assert game.steam_positive_pct == 98.0
    assert sorted(game.genres) == ["Action", "RPG"]
    assert game.developers == ["Supergiant Games"]


def test_reads_a_non_steam_igdb_game(tmp_path: Path) -> None:
    """An IGDB game with no Steam link is still a canonical game (null stats)."""
    path = write_prepared_parquet(
        tmp_path / "g.parquet",
        [game_row(igdb_id=200, steam_appid=None, title="Console Exclusive")],
    )
    game = read_canonical_games(path)[0]
    assert game.igdb_id == 200
    assert game.steam_appid is None
    assert game.steam_positive_pct is None


def test_reads_a_steam_only_game(tmp_path: Path) -> None:
    path = write_prepared_parquet(
        tmp_path / "g.parquet",
        [game_row(igdb_id=None, steam_appid=555, title="Steam Indie", steam_positive_pct=97.0)],
    )
    game = read_canonical_games(path)[0]
    assert game.igdb_id is None
    assert game.steam_appid == 555
    assert game.steam_positive_pct == 97.0


def test_reads_many_rows(tmp_path: Path) -> None:
    path = write_prepared_parquet(
        tmp_path / "g.parquet",
        [game_row(igdb_id=i, title=f"Game {i}") for i in range(1, 6)],
    )
    assert len(read_canonical_games(path)) == 5

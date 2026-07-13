"""End-to-end seed_games command — prepared parquet on disk → Postgres, idempotent."""

from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from games.models import Game
from games.tests.seed_helpers import game_row, write_prepared_parquet

pytestmark = pytest.mark.django_db


def test_seed_command_loads_a_parquet_into_postgres(tmp_path: Path, settings: Any) -> None:
    path = write_prepared_parquet(
        tmp_path / "g.parquet",
        [
            game_row(igdb_id=1, steam_appid=10, title="Celeste", steam_positive_pct=98.0),
            game_row(igdb_id=None, steam_appid=20, title="Steam Only"),
        ],
    )
    settings.PARQUET_SOURCE_URL = path

    call_command("seed_games")

    assert Game.objects.count() == 2
    celeste = Game.objects.get(igdb_id=1)
    assert celeste.steam_appid == 10
    assert celeste.steam_positive_pct == 98.0
    assert Game.objects.get(steam_appid=20).igdb_id is None


def test_seed_command_is_idempotent(tmp_path: Path, settings: Any) -> None:
    path = write_prepared_parquet(tmp_path / "g.parquet", [game_row(igdb_id=1, title="Hades")])
    settings.PARQUET_SOURCE_URL = path

    call_command("seed_games")
    call_command("seed_games")

    assert Game.objects.filter(igdb_id=1).count() == 1


def test_seed_command_accepts_source_argument(tmp_path: Path, settings: Any) -> None:
    """Launcher-agnostic: the source can be passed explicitly (Prefect etc.)."""
    settings.PARQUET_SOURCE_URL = ""
    path = write_prepared_parquet(tmp_path / "explicit.parquet", [game_row(igdb_id=7, title="Arg")])

    call_command("seed_games", source=path)

    assert Game.objects.filter(igdb_id=7).exists()


def test_seed_command_errors_when_no_source_configured(settings: Any) -> None:
    settings.PARQUET_SOURCE_URL = ""
    with pytest.raises(CommandError):
        call_command("seed_games")

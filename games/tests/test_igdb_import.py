"""import_igdb_game — fetch a missing game from IGDB and create it locally."""

from typing import Any

import pytest

from games.igdb import IGDBClient, import_igdb_game
from games.models import Game, GameCompany, GameEngine, GameGenre

pytestmark = pytest.mark.django_db

CELESTE = {
    "id": 26226,
    "name": "Celeste",
    "first_release_date": 1516924800,  # 2018-01-26
    "summary": "Help Madeline climb a mountain.",
    "genres": [{"name": "Platformer"}],
    "game_engines": [{"name": "XNA"}],
    "involved_companies": [
        {"company": {"name": "Maddy Makes Games"}, "developer": True, "publisher": True},
    ],
}


class _FakeClient(IGDBClient):
    def __init__(self, game: dict[str, Any] | None) -> None:
        super().__init__(client_id="x", client_secret="y")
        self._game = game

    def get_game(self, igdb_id: int) -> dict[str, Any] | None:
        return self._game


def test_import_creates_a_game_marked_igdb_live() -> None:
    game = import_igdb_game(26226, client=_FakeClient(CELESTE))

    assert game is not None
    assert game.igdb_id == 26226
    assert game.title == "Celeste"
    assert game.source == Game.Source.IGDB_LIVE
    assert game.last_synced_at is not None
    genre_names = list(GameGenre.objects.filter(game=game).values_list("genre__name", flat=True))
    assert genre_names == ["Platformer"]
    assert GameEngine.objects.filter(game=game).count() == 1
    assert GameCompany.objects.filter(game=game).count() == 2  # developer + publisher


def test_import_is_idempotent() -> None:
    import_igdb_game(26226, client=_FakeClient(CELESTE))
    import_igdb_game(26226, client=_FakeClient(CELESTE))
    assert Game.objects.filter(igdb_id=26226).count() == 1


def test_import_returns_none_when_igdb_has_no_such_game() -> None:
    assert import_igdb_game(999999, client=_FakeClient(None)) is None
    assert Game.objects.count() == 0

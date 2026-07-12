"""Game/Company model rules — docs/04-DATABASE-SCHEMA.md §3–6."""

import pytest
from django.contrib.postgres.search import TrigramSimilarity
from django.db import IntegrityError

from games.models import Game

pytestmark = pytest.mark.django_db


def test_external_ids_nullable_but_unique():
    # Several games without external IDs may coexist (future manual games)…
    Game.objects.create(title="Alpha", source=Game.Source.MANUAL)
    Game.objects.create(title="Beta", source=Game.Source.MANUAL)
    # …but a duplicated igdb_id is rejected.
    Game.objects.create(title="Gamma", igdb_id=42, source=Game.Source.MANUAL)
    with pytest.raises(IntegrityError):
        Game.objects.create(title="Delta", igdb_id=42, source=Game.Source.MANUAL)


def test_slug_generated_and_collision_suffixed():
    first = Game.objects.create(title="Dark Souls", source=Game.Source.MANUAL)
    second = Game.objects.create(title="Dark Souls", igdb_id=7, source=Game.Source.MANUAL)
    assert first.slug == "dark-souls"
    assert second.slug == "dark-souls-2"


def test_trigram_search_tolerates_typos():
    """The pg_trgm extension is live: 'hade' finds 'Hades'."""
    Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    Game.objects.create(title="Celeste", source=Game.Source.MANUAL)

    matches = (
        Game.objects.annotate(similarity=TrigramSimilarity("title", "hade"))
        .filter(similarity__gt=0.3)
        .order_by("-similarity")
    )
    assert [game.title for game in matches] == ["Hades"]

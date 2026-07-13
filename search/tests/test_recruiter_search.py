"""Recruiter search — the product promise, non-negotiable test zone #2.

Finds public people by *properties of the games they worked on* crossed with
their discipline (docs/01-DESIGN.md §3.6). Filters are optional and combine;
rating is a filter, never a default sort.
"""

from datetime import date

import pytest

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Engine, Game, GameEngine, GameGenre, Genre
from search.services import recruiter_search

pytestmark = pytest.mark.django_db


@pytest.fixture
def disciplines() -> dict[str, Discipline]:
    return {d.name: d for d in Discipline.objects.all()}


def _make_person(email: str, name: str, **kwargs: object) -> User:
    return User.objects.create_user(email=email, password="x", display_name=name, **kwargs)


def _credit(user: User, game: Game, discipline: Discipline, **kwargs: object) -> Contribution:
    kwargs.setdefault("job_title", "Dev")
    kwargs.setdefault("start_date", date(2020, 1, 1))
    return Contribution.objects.create(user=user, game=game, discipline=discipline, **kwargs)


def test_filters_by_discipline_and_engine(disciplines: dict[str, Discipline]) -> None:
    unreal = Engine.objects.create(name="Unreal Engine")
    unreal_game = Game.objects.create(title="UE Game", source=Game.Source.MANUAL)
    GameEngine.objects.create(game=unreal_game, engine=unreal)
    unity_game = Game.objects.create(title="Unity Game", source=Game.Source.MANUAL)

    programmer = _make_person("p@example.com", "Unreal Programmer")
    _credit(programmer, unreal_game, disciplines["Programming"])
    # Same person, different engine game as an artist — should NOT match the cross.
    artist = _make_person("a@example.com", "Unity Artist")
    _credit(artist, unity_game, disciplines["Art"])

    results = list(
        recruiter_search(discipline_id=disciplines["Programming"].pk, engine_id=unreal.pk)
    )

    assert results == [programmer]


def test_the_cross_is_within_a_single_contribution(disciplines: dict[str, Discipline]) -> None:
    """'Unreal' + 'Programming' means ONE credit is both — not two separate ones."""
    unreal = Engine.objects.create(name="Unreal Engine")
    unreal_game = Game.objects.create(title="UE Game", source=Game.Source.MANUAL)
    GameEngine.objects.create(game=unreal_game, engine=unreal)
    other_game = Game.objects.create(title="Other", source=Game.Source.MANUAL)

    person = _make_person("x@example.com", "Split Person")
    _credit(person, unreal_game, disciplines["Art"])  # Unreal, but as Art
    _credit(person, other_game, disciplines["Programming"])  # Programming, but not Unreal

    results = list(
        recruiter_search(discipline_id=disciplines["Programming"].pk, engine_id=unreal.pk)
    )

    assert results == []  # no single credit is both Unreal AND Programming


def test_filters_by_genre(disciplines: dict[str, Discipline]) -> None:
    rpg = Genre.objects.create(name="RPG")
    rpg_game = Game.objects.create(title="RPG Game", source=Game.Source.MANUAL)
    GameGenre.objects.create(game=rpg_game, genre=rpg)

    person = _make_person("p@example.com", "RPG Dev")
    _credit(person, rpg_game, disciplines["Design"])

    assert list(recruiter_search(genre_id=rpg.pk)) == [person]
    assert list(recruiter_search(genre_id=rpg.pk + 999)) == []


def test_filters_by_minimum_rating(disciplines: dict[str, Discipline]) -> None:
    hit = Game.objects.create(title="Hit", steam_positive_pct=95, source=Game.Source.MANUAL)
    flop = Game.objects.create(title="Flop", steam_positive_pct=40, source=Game.Source.MANUAL)
    star = _make_person("s@example.com", "On A Hit")
    _credit(star, hit, disciplines["Design"])
    talented = _make_person("t@example.com", "On A Flop")
    _credit(talented, flop, disciplines["Design"])

    results = list(recruiter_search(min_rating=70))

    assert star in results
    assert talented not in results


def test_open_to_work_filter(disciplines: dict[str, Discipline]) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    seeker = _make_person("s@example.com", "Seeker", open_to_work=True)
    employed = _make_person("e@example.com", "Employed", open_to_work=False)
    _credit(seeker, game, disciplines["Design"])
    _credit(employed, game, disciplines["Design"])

    results = list(recruiter_search(open_to_work=True))

    assert results == [seeker]


def test_never_returns_private_or_inactive(disciplines: dict[str, Discipline]) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    private = _make_person("pr@example.com", "Private", profile_public=False)
    _credit(private, game, disciplines["Design"])
    inactive = _make_person("in@example.com", "Inactive")
    _credit(inactive, game, disciplines["Design"], status=Contribution.Status.REMOVED)

    results = list(recruiter_search(discipline_id=disciplines["Design"].pk))

    assert private not in results
    assert inactive not in results


def test_a_person_appears_once_despite_multiple_matching_credits(
    disciplines: dict[str, Discipline],
) -> None:
    game1 = Game.objects.create(title="G1", source=Game.Source.MANUAL)
    game2 = Game.objects.create(title="G2", source=Game.Source.MANUAL)
    person = _make_person("p@example.com", "Prolific")
    _credit(person, game1, disciplines["Design"])
    _credit(person, game2, disciplines["Design"])

    results = list(recruiter_search(discipline_id=disciplines["Design"].pk))

    assert results == [person]  # DISTINCT — not duplicated


def test_no_filters_returns_all_matching_public_people(
    disciplines: dict[str, Discipline],
) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    a = _make_person("a@example.com", "Aaron")
    b = _make_person("b@example.com", "Bea")
    _credit(a, game, disciplines["Design"])
    _credit(b, game, disciplines["Art"])

    results = list(recruiter_search())

    assert set(results) == {a, b}

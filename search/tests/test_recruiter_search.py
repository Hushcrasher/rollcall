"""Recruiter search — the product promise, non-negotiable test zone #2.

Finds public people by *properties of the games they worked on* crossed with
their discipline (docs/01-DESIGN.md §3.6). Multi-value facets are OR within,
AND across; every credit-level filter applies to the SAME contribution.
Results are assembled PersonResult cards, paginated, ordered by display_name
(rating is a filter, never a sort)."""

from datetime import date
from typing import Any

import pytest

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Company, Engine, Game, GameEngine, GameGenre, Genre
from search.services import (
    MATCHING_CREDITS_SHOWN,
    RESULTS_PER_PAGE,
    PersonResult,
    _percentage_shares,
    recruiter_search,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def disciplines() -> dict[str, Discipline]:
    return {d.name: d for d in Discipline.objects.all()}


def _make_person(email: str, name: str, **kwargs: object) -> User:
    return User.objects.create_user(email=email, password="x", display_name=name, **kwargs)


def _credit(
    user: User, game: Game | None, discipline: Discipline, **kwargs: object
) -> Contribution:
    kwargs.setdefault("job_title", "Dev")
    kwargs.setdefault("start_date", date(2020, 1, 1))
    return Contribution.objects.create(user=user, game=game, discipline=discipline, **kwargs)


def _engine_game(title: str, *engines: Engine) -> Game:
    game = Game.objects.create(title=title, source=Game.Source.MANUAL)
    for engine in engines:
        GameEngine.objects.create(game=game, engine=engine)
    return game


def _genre_game(title: str, *genres: Genre) -> Game:
    game = Game.objects.create(title=title, source=Game.Source.MANUAL)
    for genre in genres:
        GameGenre.objects.create(game=game, genre=genre)
    return game


def _users(**kwargs: Any) -> list[User]:
    return [r.user for r in recruiter_search(**kwargs).results]


# ---------------------------------------------------------------- filters


def test_filters_by_discipline_and_engine(disciplines: dict[str, Discipline]) -> None:
    unreal = Engine.objects.create(name="Unreal Engine")
    unreal_game = _engine_game("UE Game", unreal)
    unity_game = Game.objects.create(title="Unity Game", source=Game.Source.MANUAL)

    programmer = _make_person("p@example.com", "Unreal Programmer")
    _credit(programmer, unreal_game, disciplines["Programming"])
    artist = _make_person("a@example.com", "Unity Artist")
    _credit(artist, unity_game, disciplines["Art"])

    results = _users(discipline_id=disciplines["Programming"].pk, engine_ids=[unreal.pk])

    assert results == [programmer]


def test_the_cross_is_within_a_single_contribution(disciplines: dict[str, Discipline]) -> None:
    """'Unreal' + 'Programming' means ONE credit is both — not two separate ones."""
    unreal = Engine.objects.create(name="Unreal Engine")
    unreal_game = _engine_game("UE Game", unreal)
    other_game = Game.objects.create(title="Other", source=Game.Source.MANUAL)

    person = _make_person("x@example.com", "Split Person")
    _credit(person, unreal_game, disciplines["Art"])  # Unreal, but as Art
    _credit(person, other_game, disciplines["Programming"])  # Programming, but not Unreal

    assert _users(discipline_id=disciplines["Programming"].pk, engine_ids=[unreal.pk]) == []


def test_the_cross_is_within_a_single_contribution_with_multi_values(
    disciplines: dict[str, Discipline],
) -> None:
    """The same-credit rule survives multi-value facets: (Unreal OR Unity) AND
    (RPG OR Racing) must hold on ONE credit, not be spread across two."""
    unreal = Engine.objects.create(name="Unreal Engine")
    unity = Engine.objects.create(name="Unity")
    rpg = Genre.objects.create(name="RPG")
    racing = Genre.objects.create(name="Racing")

    engine_only = _engine_game("Engine Only", unreal, unity)  # engines, no genre
    genre_only = _genre_game("Genre Only", rpg, racing)  # genres, no engine

    split = _make_person("s@example.com", "Split Person")
    _credit(split, engine_only, disciplines["Design"])
    _credit(split, genre_only, disciplines["Design"])

    both = _make_person("b@example.com", "Both Person")
    both_game = _engine_game("Both", unity)
    GameGenre.objects.create(game=both_game, genre=racing)
    _credit(both, both_game, disciplines["Design"])

    results = _users(engine_ids=[unreal.pk, unity.pk], genre_ids=[rpg.pk, racing.pk])

    assert results == [both]  # `split` satisfies each facet, but never on one credit


def test_or_within_engines(disciplines: dict[str, Discipline]) -> None:
    unreal = Engine.objects.create(name="Unreal Engine")
    unity = Engine.objects.create(name="Unity")
    godot = Engine.objects.create(name="Godot")

    ue_person = _make_person("ue@example.com", "A UE Person")
    _credit(ue_person, _engine_game("UE Game", unreal), disciplines["Design"])
    unity_person = _make_person("un@example.com", "B Unity Person")
    _credit(unity_person, _engine_game("Unity Game", unity), disciplines["Design"])
    godot_person = _make_person("go@example.com", "C Godot Person")
    _credit(godot_person, _engine_game("Godot Game", godot), disciplines["Design"])

    results = _users(engine_ids=[unreal.pk, unity.pk])

    assert results == [ue_person, unity_person]  # OR within the facet; godot excluded


def test_or_within_genres(disciplines: dict[str, Discipline]) -> None:
    rpg = Genre.objects.create(name="RPG")
    racing = Genre.objects.create(name="Racing")
    puzzle = Genre.objects.create(name="Puzzle")

    rpg_person = _make_person("r@example.com", "A RPG Person")
    _credit(rpg_person, _genre_game("RPG Game", rpg), disciplines["Design"])
    racing_person = _make_person("c@example.com", "B Racing Person")
    _credit(racing_person, _genre_game("Racing Game", racing), disciplines["Design"])
    puzzle_person = _make_person("z@example.com", "C Puzzle Person")
    _credit(puzzle_person, _genre_game("Puzzle Game", puzzle), disciplines["Design"])

    assert _users(genre_ids=[rpg.pk, racing.pk]) == [rpg_person, racing_person]


def test_multi_engine_game_matches_once(disciplines: dict[str, Discipline]) -> None:
    """A game tagged with BOTH selected engines must not duplicate the person."""
    unreal = Engine.objects.create(name="Unreal Engine")
    unity = Engine.objects.create(name="Unity")
    person = _make_person("m@example.com", "Multi Engine")
    credit = _credit(person, _engine_game("Hybrid", unreal, unity), disciplines["Design"])

    page = recruiter_search(engine_ids=[unreal.pk, unity.pk])

    assert [r.user for r in page.results] == [person]
    assert page.total == 1
    assert page.results[0].matching_credits_total == 1  # one credit, not two
    assert page.results[0].matching_credits == [credit]


def test_filters_by_country(disciplines: dict[str, Discipline]) -> None:
    """Country is a PERSON-level filter, not a credit-level one."""
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    french = _make_person("fr@example.com", "French Person", country="FR")
    _credit(french, game, disciplines["Design"])
    swedish = _make_person("se@example.com", "Swedish Person", country="SE")
    _credit(swedish, game, disciplines["Design"])
    nowhere = _make_person("nw@example.com", "No Country")
    _credit(nowhere, game, disciplines["Design"])

    assert _users(countries=["FR"]) == [french]
    assert _users(countries=["FR", "SE"]) == [french, swedish]  # `nowhere` excluded


def test_filters_by_minimum_rating_on_steam(disciplines: dict[str, Discipline]) -> None:
    hit = Game.objects.create(title="Hit", steam_positive_pct=95, source=Game.Source.MANUAL)
    flop = Game.objects.create(title="Flop", steam_positive_pct=40, source=Game.Source.MANUAL)
    star = _make_person("s@example.com", "On A Hit")
    _credit(star, hit, disciplines["Design"])
    talented = _make_person("t@example.com", "On A Flop")
    _credit(talented, flop, disciplines["Design"])

    results = _users(min_rating=70)

    assert star in results
    assert talented not in results


def test_minimum_rating_accepts_igdb_when_steam_is_absent(
    disciplines: dict[str, Discipline],
) -> None:
    """Rating is Steam OR IGDB — a game scored only by IGDB still qualifies."""
    igdb_hit = Game.objects.create(title="IGDB Hit", igdb_rating=88, source=Game.Source.MANUAL)
    igdb_flop = Game.objects.create(title="IGDB Flop", igdb_rating=30, source=Game.Source.MANUAL)
    unrated = Game.objects.create(title="Unrated", source=Game.Source.MANUAL)
    star = _make_person("s@example.com", "A On IGDB Hit")
    _credit(star, igdb_hit, disciplines["Design"])
    weak = _make_person("w@example.com", "B On IGDB Flop")
    _credit(weak, igdb_flop, disciplines["Design"])
    unknown = _make_person("u@example.com", "C On Unrated")
    _credit(unknown, unrated, disciplines["Design"])

    results = _users(min_rating=70)

    assert results == [star]  # min_rating requires rating data — that's why the form min is 1


def test_filters_by_year_from(disciplines: dict[str, Discipline]) -> None:
    """year_from is credit-level: it matches the credit's START year."""
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    recent = _make_person("r@example.com", "A Recent")
    _credit(recent, game, disciplines["Design"], start_date=date(2021, 6, 1))
    old = _make_person("o@example.com", "B Old")
    _credit(old, game, disciplines["Design"], start_date=date(2005, 1, 1))
    boundary = _make_person("b@example.com", "C Boundary")
    _credit(boundary, game, disciplines["Design"], start_date=date(2015, 1, 1))

    assert _users(year_from=2015) == [recent, boundary]  # gte — 2015 is included


def test_open_to_work_filter(disciplines: dict[str, Discipline]) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    seeker = _make_person("s@example.com", "Seeker", open_to_work=True)
    employed = _make_person("e@example.com", "Employed", open_to_work=False)
    _credit(seeker, game, disciplines["Design"])
    _credit(employed, game, disciplines["Design"])

    assert _users(open_to_work=True) == [seeker]


def test_open_to_work_false_does_not_filter(disciplines: dict[str, Discipline]) -> None:
    """Unchecked means "I don't care", not "only people who are NOT looking"."""
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    seeker = _make_person("s@example.com", "A Seeker", open_to_work=True)
    employed = _make_person("e@example.com", "B Employed", open_to_work=False)
    _credit(seeker, game, disciplines["Design"])
    _credit(employed, game, disciplines["Design"])

    assert _users(discipline_id=disciplines["Design"].pk, open_to_work=False) == [seeker, employed]


def test_never_returns_private_or_inactive(disciplines: dict[str, Discipline]) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    private = _make_person("pr@example.com", "Private", profile_public=False)
    _credit(private, game, disciplines["Design"])
    inactive = _make_person("in@example.com", "Inactive")
    _credit(inactive, game, disciplines["Design"], status=Contribution.Status.REMOVED)

    # Both people would match the discipline; neither may surface.
    assert _users(discipline_id=disciplines["Design"].pk) == []


def test_a_person_appears_once_despite_multiple_matching_credits(
    disciplines: dict[str, Discipline],
) -> None:
    game1 = Game.objects.create(title="G1", source=Game.Source.MANUAL)
    game2 = Game.objects.create(title="G2", source=Game.Source.MANUAL)
    person = _make_person("p@example.com", "Prolific")
    _credit(person, game1, disciplines["Design"])
    _credit(person, game2, disciplines["Design"])

    page = recruiter_search(discipline_id=disciplines["Design"].pk)

    assert [r.user for r in page.results] == [person]
    assert page.total == 1


def test_no_filters_returns_all_matching_public_people(
    disciplines: dict[str, Discipline],
) -> None:
    """Service-level: the >=1-filter rule is enforced by the FORM, not here."""
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    a = _make_person("a@example.com", "Aaron")
    b = _make_person("b@example.com", "Bea")
    _credit(a, game, disciplines["Design"])
    _credit(b, game, disciplines["Art"])

    assert set(_users()) == {a, b}


def test_credits_without_a_game_are_not_searchable(disciplines: dict[str, Discipline]) -> None:
    """A company-only credit carries no game properties to search on — but it
    is still part of the career, so the stats count it. That asymmetry is
    deliberate: search cuts on game properties, the card summarises a career."""
    company = Company.objects.create(name="Studio")
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)

    company_only = _make_person("c@example.com", "Company Only")
    _credit(company_only, None, disciplines["Design"], company=company)

    both = _make_person("b@example.com", "Has A Game Credit")
    _credit(both, game, disciplines["Design"])
    _credit(both, None, disciplines["Design"], company=company)

    results = recruiter_search(discipline_id=disciplines["Design"].pk).results

    assert [r.user for r in results] == [both]  # company_only has nothing to match on
    assert results[0].matching_credits_total == 1  # only the game credit matched
    assert results[0].credits_count == 2  # ...but both count as career credits
    assert results[0].games_count == 1


# ---------------------------------------------------------------- cards


def _single_result(**kwargs: Any) -> PersonResult:
    page = recruiter_search(**kwargs)
    assert len(page.results) == 1
    return page.results[0]


def test_matching_credits_are_the_filter_satisfying_ones(
    disciplines: dict[str, Discipline],
) -> None:
    unreal = Engine.objects.create(name="Unreal Engine")
    ue_game = _engine_game("UE Game", unreal)
    other = Game.objects.create(title="Other Game", source=Game.Source.MANUAL)
    person = _make_person("p@example.com", "Person")
    matching = _credit(person, ue_game, disciplines["Programming"], job_title="UE Dev")
    _credit(person, other, disciplines["Programming"], job_title="Other Dev")

    result = _single_result(engine_ids=[unreal.pk])

    assert result.matching_credits == [matching]
    assert result.matching_credits_total == 1
    assert result.more_credits_count == 0
    assert result.credits_count == 2  # career stats stay career-wide
    assert result.games_count == 2


def test_career_stats_count_all_active_credits(disciplines: dict[str, Discipline]) -> None:
    """Career stats are career-wide, and only active credits count. Two credits
    on the SAME game are two credits but one game."""
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    other = Game.objects.create(title="Other", source=Game.Source.MANUAL)
    person = _make_person("p@example.com", "Person")
    _credit(person, game, disciplines["Design"], job_title="Designer")
    _credit(person, game, disciplines["Design"], job_title="Lead Designer")
    _credit(person, other, disciplines["Design"])
    _credit(person, other, disciplines["Design"], status=Contribution.Status.REMOVED)

    result = _single_result(discipline_id=disciplines["Design"].pk)

    assert result.credits_count == 3  # the removed one is invisible
    assert result.games_count == 2


def test_matching_credits_are_capped_with_total(disciplines: dict[str, Discipline]) -> None:
    person = _make_person("p@example.com", "Busy")
    for i in range(MATCHING_CREDITS_SHOWN + 2):
        game = Game.objects.create(title=f"Game {i}", source=Game.Source.MANUAL)
        _credit(person, game, disciplines["Design"], start_date=date(2010 + i, 1, 1))

    result = _single_result(discipline_id=disciplines["Design"].pk)

    assert len(result.matching_credits) == MATCHING_CREDITS_SHOWN
    assert result.matching_credits_total == MATCHING_CREDITS_SHOWN + 2
    assert result.more_credits_count == 2
    # Most recent first, and it is the newest ones that are kept.
    starts = [c.start_date for c in result.matching_credits]
    assert starts == [date(2014, 1, 1), date(2013, 1, 1), date(2012, 1, 1)]


def test_matching_credits_order_is_stable_for_same_month_credits(
    disciplines: dict[str, Discipline],
) -> None:
    """Dates are month precision, so ties are common — and the tie decides
    WHICH 3 credits the card shows. Without the -id secondary key, Postgres
    order is unspecified."""
    same_day = date(2020, 1, 1)
    person = _make_person("p@example.com", "Tied")
    for i in range(5):
        game = Game.objects.create(title=f"G{i}", source=Game.Source.MANUAL)
        _credit(person, game, disciplines["Design"], start_date=same_day)

    result = _single_result(discipline_id=disciplines["Design"].pk)
    ids = [c.pk for c in result.matching_credits]

    assert ids == sorted(ids, reverse=True)  # newest-inserted first, deterministically


def test_years_active_with_open_end_is_present(disciplines: dict[str, Discipline]) -> None:
    game1 = Game.objects.create(title="G1", source=Game.Source.MANUAL)
    game2 = Game.objects.create(title="G2", source=Game.Source.MANUAL)
    person = _make_person("p@example.com", "Veteran")
    _credit(
        person, game1, disciplines["Design"], start_date=date(2015, 3, 1), end_date=date(2018, 1, 1)
    )
    _credit(person, game2, disciplines["Design"], start_date=date(2019, 1, 1))  # open end

    result = _single_result(discipline_id=disciplines["Design"].pk)

    assert result.first_year == 2015
    assert result.last_year is None  # open end = present


def test_years_active_all_ended(disciplines: dict[str, Discipline]) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    person = _make_person("p@example.com", "Past")
    _credit(
        person, game, disciplines["Design"], start_date=date(2012, 1, 1), end_date=date(2014, 6, 1)
    )

    result = _single_result(discipline_id=disciplines["Design"].pk)

    assert result.first_year == 2012
    assert result.last_year == 2014


def test_years_active_are_career_wide_not_filter_scoped(
    disciplines: dict[str, Discipline],
) -> None:
    """The card summarises a career, so the years span credits the filters
    never matched."""
    unreal = Engine.objects.create(name="Unreal Engine")
    ue_game = _engine_game("UE Game", unreal)
    old_game = Game.objects.create(title="Old", source=Game.Source.MANUAL)
    person = _make_person("p@example.com", "Veteran")
    _credit(
        person,
        old_game,
        disciplines["Design"],
        start_date=date(2001, 1, 1),
        end_date=date(2004, 1, 1),
    )
    _credit(
        person,
        ue_game,
        disciplines["Design"],
        start_date=date(2020, 1, 1),
        end_date=date(2022, 1, 1),
    )

    result = _single_result(engine_ids=[unreal.pk])

    assert result.matching_credits_total == 1
    assert (result.first_year, result.last_year) == (2001, 2022)


def test_engine_shares_sum_to_100_top3_plus_other(disciplines: dict[str, Discipline]) -> None:
    person = _make_person("p@example.com", "Poly")
    engines = [Engine.objects.create(name=f"Engine {i}") for i in range(5)]
    # 4 games on Engine 0, then 1 game each on Engines 1-4 → 8 pairs total.
    for i in range(4):
        _credit(person, _engine_game(f"E0 Game {i}", engines[0]), disciplines["Design"])
    for i, engine in enumerate(engines[1:], start=1):
        _credit(person, _engine_game(f"Game {i}", engine), disciplines["Design"])

    result = _single_result(discipline_id=disciplines["Design"].pk)

    assert sum(pct for _, pct in result.engine_shares) == 100
    assert len(result.engine_shares) == 4  # top 3 + other
    assert result.engine_shares[0] == ("Engine 0", 50)  # 4 of 8 pairs
    assert result.engine_shares[-1][0] == "other"  # 5 engines → top 3 + other


def test_engine_shares_count_distinct_games_not_credits(
    disciplines: dict[str, Discipline],
) -> None:
    """Repartition is over distinct (game, engine) pairs — three credits on one
    Unreal game must not make Unreal look like 75% of a career."""
    unreal = Engine.objects.create(name="Unreal Engine")
    unity = Engine.objects.create(name="Unity")
    ue_game = _engine_game("UE Game", unreal)
    unity_game = _engine_game("Unity Game", unity)
    person = _make_person("p@example.com", "Person")
    for title in ("Dev", "Lead", "Director"):
        _credit(person, ue_game, disciplines["Design"], job_title=title)
    _credit(person, unity_game, disciplines["Design"])

    result = _single_result(discipline_id=disciplines["Design"].pk)

    # 50/50 — 4 credits but only 2 (game, engine) pairs. Ties rank by name.
    assert result.engine_shares == [("Unity", 50), ("Unreal Engine", 50)]


def test_engine_shares_are_career_wide_and_ignore_inactive_credits(
    disciplines: dict[str, Discipline],
) -> None:
    unreal = Engine.objects.create(name="Unreal Engine")
    unity = Engine.objects.create(name="Unity")
    person = _make_person("p@example.com", "Person")
    _credit(person, _engine_game("UE Game", unreal), disciplines["Design"])
    # Career-wide: this Unity credit shows in the shares even though the
    # Unreal filter never matched it...
    _credit(person, _engine_game("Unity Game", unity), disciplines["Design"])
    # ...but a removed credit contributes nothing.
    _credit(
        person,
        _engine_game("Removed Game", unity),
        disciplines["Design"],
        status=Contribution.Status.REMOVED,
    )

    result = _single_result(engine_ids=[unreal.pk])

    assert result.engine_shares == [("Unity", 50), ("Unreal Engine", 50)]


def test_engine_shares_absent_without_engine_data(disciplines: dict[str, Discipline]) -> None:
    game = Game.objects.create(title="No Engine", source=Game.Source.MANUAL)
    person = _make_person("p@example.com", "Person")
    _credit(person, game, disciplines["Design"])

    result = _single_result(discipline_id=disciplines["Design"].pk)

    assert result.engine_shares == []


# ------------------------------------------------------- percentage arithmetic


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        # Nothing to share.
        ({}, []),
        # One engine takes the lot.
        ({"a": 5}, [("a", 100)]),
        # 3 equal thirds cannot all be 33 — largest remainder pushes one to 34.
        ({"a": 1, "b": 1, "c": 1}, [("a", 34), ("b", 33), ("c", 33)]),
        # Exact, no remainder to hand out.
        ({"a": 3, "b": 1}, [("a", 75), ("b", 25)]),
        # Flooring loses 2 points; the two largest fractions (tied, so
        # name-ordered) get them. 7 entries → top 3 + other.
        (
            {"a": 1, "b": 1, "c": 1, "d": 1, "e": 1, "f": 1, "g": 1},
            [("a", 15), ("b", 15), ("c", 14), ("other", 56)],
        ),
        # A share that rounds to 0 is dropped, not shown as "0%".
        ({"a": 200, "b": 1}, [("a", 100)]),
    ],
)
def test_percentage_shares(counts: dict[str, int], expected: list[tuple[str, int]]) -> None:
    assert _percentage_shares(counts) == expected


@pytest.mark.parametrize(
    "counts",
    [
        {"a": 1, "b": 1, "c": 1},
        {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6, "g": 7},
        {"a": 1, "b": 1, "c": 1, "d": 1, "e": 1, "f": 1, "g": 1},
        {"a": 17},
        {"a": 1, "b": 1000000},
        {"a": 1, "b": 1, "c": 97},
        {f"e{i}": 1 for i in range(201)},
        {f"e{i}": i + 1 for i in range(13)},
    ],
)
def test_percentage_shares_always_sum_to_100(counts: dict[str, int]) -> None:
    """The whole point of largest-remainder rounding: a displayed repartition
    that doesn't add up to 100 looks broken."""
    assert sum(pct for _, pct in _percentage_shares(counts)) == 100


def test_percentage_shares_ranks_descending() -> None:
    shares = _percentage_shares({"small": 1, "big": 6, "mid": 3})
    assert shares == [("big", 60), ("mid", 30), ("small", 10)]


# ---------------------------------------------------------------- pagination


def test_results_are_paginated_and_ordered_by_display_name(
    disciplines: dict[str, Discipline],
) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    for i in range(RESULTS_PER_PAGE + 5):
        person = _make_person(f"u{i}@example.com", f"Person {i:02d}")
        _credit(person, game, disciplines["Design"])

    first = recruiter_search(discipline_id=disciplines["Design"].pk, page=1)
    second = recruiter_search(discipline_id=disciplines["Design"].pk, page=2)

    assert first.total == RESULTS_PER_PAGE + 5
    assert first.num_pages == 2
    assert len(first.results) == RESULTS_PER_PAGE
    assert len(second.results) == 5
    names = [r.user.display_name for r in first.results]
    assert names == sorted(names)
    assert names[0] == "Person 00"
    assert [r.user.display_name for r in second.results][0] == "Person 20"
    assert first.has_next and not first.has_previous
    assert second.has_previous and not second.has_next


def test_rating_is_a_filter_never_a_sort(disciplines: dict[str, Discipline]) -> None:
    """No numeric score ranks people — a flop credit does not sink you below
    the alphabet."""
    hit = Game.objects.create(title="Hit", steam_positive_pct=99, source=Game.Source.MANUAL)
    ok = Game.objects.create(title="OK", steam_positive_pct=71, source=Game.Source.MANUAL)
    zoe = _make_person("z@example.com", "Zoe On A Hit")
    _credit(zoe, hit, disciplines["Design"])
    adam = _make_person("a@example.com", "Adam On An OK Game")
    _credit(adam, ok, disciplines["Design"])

    assert _users(min_rating=70) == [adam, zoe]  # alphabetical, not 99% first


def test_out_of_range_page_clamps_to_the_last_page(
    disciplines: dict[str, Discipline],
) -> None:
    """get_page() clamps high/zero/negative to the LAST page (not the first) —
    build two pages so the assertion can tell the two rules apart."""
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    for i in range(RESULTS_PER_PAGE + 5):
        _credit(_make_person(f"u{i}@example.com", f"Person {i:02d}"), game, disciplines["Design"])

    for page in (99, 0, -1):
        assert recruiter_search(discipline_id=disciplines["Design"].pk, page=page).page_number == 2


def test_junk_page_param_does_not_explode(disciplines: dict[str, Discipline]) -> None:
    """The view hands the raw GET value straight through — ?page=abc must not
    500 on a public page."""
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    _credit(_make_person("p@example.com", "Only One"), game, disciplines["Design"])

    assert recruiter_search(discipline_id=disciplines["Design"].pk, page="abc").page_number == 1
    assert recruiter_search(discipline_id=disciplines["Design"].pk, page=None).page_number == 1


def test_page_links_are_none_at_the_boundaries(disciplines: dict[str, Discipline]) -> None:
    """previous_page_number must be None on page 1, not 0 — get_page(0) clamps
    to the LAST page, so an unguarded link would jump to the end."""
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    for i in range(RESULTS_PER_PAGE + 5):
        _credit(_make_person(f"u{i}@example.com", f"Person {i:02d}"), game, disciplines["Design"])

    first = recruiter_search(discipline_id=disciplines["Design"].pk, page=1)
    last = recruiter_search(discipline_id=disciplines["Design"].pk, page=2)

    assert first.previous_page_number is None
    assert first.next_page_number == 2
    assert last.previous_page_number == 1
    assert last.next_page_number is None


def test_single_page_has_no_links_at_all(disciplines: dict[str, Discipline]) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    _credit(_make_person("p@example.com", "Only One"), game, disciplines["Design"])

    only = recruiter_search(discipline_id=disciplines["Design"].pk)

    assert only.previous_page_number is None
    assert only.next_page_number is None


def test_empty_result_page_is_empty(disciplines: dict[str, Discipline]) -> None:
    page = recruiter_search(discipline_id=disciplines["Design"].pk)

    assert page.results == []
    assert page.total == 0
    assert not page.has_next
    assert not page.has_previous


def test_assembly_does_not_grow_queries_with_the_number_of_people(
    disciplines: dict[str, Discipline], django_assert_num_queries: Any
) -> None:
    """Assembly is bounded by page size, not by N+1 per person or per credit."""
    unreal = Engine.objects.create(name="Unreal Engine")

    def build(n: int) -> None:
        for i in range(n):
            person = _make_person(f"u{n}-{i}@example.com", f"P{n}-{i}")
            for j in range(3):
                _credit(person, _engine_game(f"G{n}-{i}-{j}", unreal), disciplines["Design"])

    def read(page: Any) -> None:
        for result in page.results:
            for credit in result.matching_credits:
                assert credit.game is not None
                _ = (credit.game.title, credit.discipline.name)
            _ = (result.credits_count, result.games_count, result.engine_shares)

    build(1)
    with django_assert_num_queries(5) as ctx:
        read(recruiter_search(engine_ids=[unreal.pk]))
    baseline = len(ctx.captured_queries)

    build(4)
    with django_assert_num_queries(baseline):
        page = recruiter_search(engine_ids=[unreal.pk])
        assert len(page.results) == 5
        read(page)


def test_game_summary_is_not_fetched_for_matching_credits(
    disciplines: dict[str, Discipline], django_assert_num_queries: Any
) -> None:
    """Cards show title/job/dates, never the summary blob — and a person's
    matching credits are unbounded, so we defer it. If a card ever needs
    summary, drop the defer rather than paying a query per credit here."""
    unreal = Engine.objects.create(name="Unreal Engine")
    game = Game.objects.create(
        title="UE Game", source=Game.Source.MANUAL, summary="A very long marketing blurb."
    )
    GameEngine.objects.create(game=game, engine=unreal)
    _credit(_make_person("p@example.com", "Person"), game, disciplines["Design"])

    credit = _single_result(engine_ids=[unreal.pk]).matching_credits[0]

    with django_assert_num_queries(1):  # deferred: touching it costs a round-trip
        assert credit.game is not None  # select_related loaded it — free
        # ty resolves FK descriptors to the Field, not the related model — the
        # same accommodation accounts/github.py:189 makes.
        assert credit.game.summary == "A very long marketing blurb."  # ty: ignore[unresolved-attribute]

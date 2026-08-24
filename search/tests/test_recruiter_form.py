"""Recruiter search form — every field optional, but at least ONE is required,
so the open search has no filterless "list everyone" submit.

That rule is a UX guard, not an anti-scraping boundary — `?min_rating=1`
matches nearly everyone and is perfectly legal. The rate limit is the real
mitigation (docs/02-ARCHITECTURE.md §5). Don't let these tests grow a claim
the rule can't back."""

import pytest
from django.utils import translation

from contributions.models import Discipline
from games.models import Engine, Game, Genre
from search.forms import RecruiterSearchForm

pytestmark = pytest.mark.django_db


def test_zero_filters_is_invalid() -> None:
    form = RecruiterSearchForm({})
    assert not form.is_valid()
    assert "Pick at least one filter." in form.non_field_errors()


def test_page_param_alone_is_still_zero_filters() -> None:
    assert not RecruiterSearchForm({"page": "2"}).is_valid()


def test_each_filter_alone_satisfies_the_rule() -> None:
    """Every field must count as a filter on its own. Parametrized in spirit
    over all 8 — dropping any one from clean()'s any([...]) must fail HERE.
    (Task 5's review mutation-tested this: with only the plan's original
    tests, 4 of the 7 entries could be deleted with the suite still green.)"""
    engine = Engine.objects.create(name="Unreal Engine")
    genre = Genre.objects.create(name="RPG")
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    discipline = Discipline.objects.get(name="Design")
    for data in (
        {"discipline": str(discipline.pk)},
        {"engines": [str(engine.pk)]},
        {"genres": [str(genre.pk)]},
        {"games": [str(game.pk)]},
        {"countries": ["FR"]},
        {"min_rating": "70"},
        {"year_from": "2015"},
        {"open_to_work": "on"},
    ):
        assert RecruiterSearchForm(data).is_valid(), f"{data} should be enough"


def test_games_is_multi_select() -> None:
    hades = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    celeste = Game.objects.create(title="Celeste", source=Game.Source.MANUAL)

    form = RecruiterSearchForm({"games": [str(hades.pk), str(celeste.pk)]})

    assert form.is_valid()
    assert set(form.cleaned_data["games"]) == {hades, celeste}


def test_min_rating_zero_is_rejected_by_the_field() -> None:
    """0 reads as "I don't care" but would mean "must have rating data" —
    blank is how you say you don't care (min_value=1).

    Asserts *why* it's rejected, not just that it is: with min_value=0 the form
    would still be invalid — 0 is falsy, so the zero-filter rule would catch it
    — which is the right answer for the wrong reason and pins nothing. Only the
    field-level error pins min_value=1.
    """
    form = RecruiterSearchForm({"min_rating": "0"})
    assert not form.is_valid()
    assert "min_rating" in form.errors
    assert "Pick at least one filter." not in form.non_field_errors()


def test_field_error_does_not_also_demand_a_filter() -> None:
    form = RecruiterSearchForm({"min_rating": "200"})
    assert not form.is_valid()
    assert "Pick at least one filter." not in form.non_field_errors()


def test_country_choices_follow_the_active_language() -> None:
    """Passing `countries` directly would freeze the names at import."""
    with translation.override("fr"):
        choices = dict(RecruiterSearchForm().fields["countries"].choices)
        assert choices["DE"] == "Allemagne"


def test_engines_and_genres_are_multi_select() -> None:
    unreal = Engine.objects.create(name="Unreal Engine")
    unity = Engine.objects.create(name="Unity")
    rpg = Genre.objects.create(name="RPG")

    form = RecruiterSearchForm(
        {"engines": [str(unreal.pk), str(unity.pk)], "genres": [str(rpg.pk)]}
    )

    assert form.is_valid()
    assert set(form.cleaned_data["engines"]) == {unreal, unity}
    assert list(form.cleaned_data["genres"]) == [rpg]


def test_countries_accepts_iso_codes_and_rejects_junk() -> None:
    assert RecruiterSearchForm({"countries": ["FR", "SE"]}).is_valid()
    assert not RecruiterSearchForm({"countries": ["ZZ"]}).is_valid()


_CONFLICT = "Filter either by game criteria or by specific games, not both."


@pytest.mark.parametrize("criteria", ["genres", "min_rating", "engines"])
def test_each_game_criterion_conflicts_with_specific_games(criteria: str) -> None:
    """The two ways of naming games are alternatives, not filters that compose:
    adding a genre to a list of named games can only narrow it into nonsense.
    Parametrized so dropping any one of the three from clean() fails here."""
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    values = {
        "genres": [str(Genre.objects.create(name="RPG").pk)],
        "engines": [str(Engine.objects.create(name="Unreal Engine").pk)],
        "min_rating": "70",
    }

    form = RecruiterSearchForm({"games": [str(game.pk)], criteria: values[criteria]})

    assert not form.is_valid()
    assert _CONFLICT in form.non_field_errors()


@pytest.mark.parametrize(
    "person_filter",
    [
        {"countries": ["FR"]},
        {"year_from": "2015"},
        {"open_to_work": "on"},
    ],
)
def test_person_filters_do_not_conflict_with_specific_games(
    person_filter: dict[str, object],
) -> None:
    """The whole person section answers a different question and stays
    available in both modes (spec 2026-08-24 §7)."""
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)

    form = RecruiterSearchForm({"games": [str(game.pk)], **person_filter})

    assert form.is_valid(), form.errors


def test_discipline_does_not_conflict_with_specific_games() -> None:
    """Separate from the parametrized cases above: discipline needs a real row."""
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    discipline = Discipline.objects.get(name="Design")

    form = RecruiterSearchForm({"games": [str(game.pk)], "discipline": str(discipline.pk)})

    assert form.is_valid(), form.errors


def test_a_field_error_does_not_also_report_the_conflict() -> None:
    """Same reasoning as the zero-filter rule: a field-level error already told
    the user what is wrong.

    The broken field is `countries`, deliberately NOT one of the three
    criteria. An invalid `min_rating` would pin nothing here: Django drops a
    field that failed validation from `cleaned_data`, so `criteria` would be
    False on its own and the conflict could not fire whether the errors guard
    ran, moved, or vanished. With a real genre AND a real game submitted, the
    conflict is live and only the guard's early return suppresses it.
    """
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    genre = Genre.objects.create(name="RPG")

    form = RecruiterSearchForm(
        {"games": [str(game.pk)], "genres": [str(genre.pk)], "countries": ["ZZ"]}
    )

    assert not form.is_valid()
    assert "countries" in form.errors
    assert _CONFLICT not in form.non_field_errors()

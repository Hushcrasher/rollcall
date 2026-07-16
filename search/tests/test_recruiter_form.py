"""Recruiter search form — every field optional, but at least ONE is required,
so the open search has no filterless "list everyone" submit.

That rule is a UX guard, not an anti-scraping boundary — `?min_rating=1`
matches nearly everyone and is perfectly legal. The rate limit is the real
mitigation (docs/02-ARCHITECTURE.md §5). Don't let these tests grow a claim
the rule can't back."""

import pytest
from django.utils import translation

from contributions.models import Discipline
from games.models import Engine, Genre
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
    over all 7 — dropping any one from clean()'s any([...]) must fail HERE.
    (Task 5's review mutation-tested this: with only the plan's original
    tests, 4 of the 7 entries could be deleted with the suite still green.)"""
    engine = Engine.objects.create(name="Unreal Engine")
    genre = Genre.objects.create(name="RPG")
    discipline = Discipline.objects.get(name="Design")
    for data in (
        {"discipline": str(discipline.pk)},
        {"engines": [str(engine.pk)]},
        {"genres": [str(genre.pk)]},
        {"countries": ["FR"]},
        {"min_rating": "70"},
        {"year_from": "2015"},
        {"open_to_work": "on"},
    ):
        assert RecruiterSearchForm(data).is_valid(), f"{data} should be enough"


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

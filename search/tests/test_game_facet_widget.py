"""The `games` facet's chip widget.

The base TypeaheadSelectMultiple builds its label map by iterating
`self.choices` — correct for Engine, Genre and the 249 countries, ruinous for
Game: the catalogue is ~391k rows and would be materialised on every render of
the home page. These tests pin the targeted lookup that replaces it, and the
querystring shapes that must not reach the database as-is.
"""

from typing import Any

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from games.models import Game
from search.forms import RecruiterSearchForm

pytestmark = pytest.mark.django_db


def test_selected_games_render_as_chips(client: Client) -> None:
    hades = Game.objects.create(title="Hades", source=Game.Source.MANUAL)

    rendered = str(RecruiterSearchForm({"games": [str(hades.pk)]})["games"])

    assert f'<input type="hidden" name="games" value="{hades.pk}">' in rendered
    assert "Hades" in rendered


def test_game_chips_are_ordered_as_given() -> None:
    """Querystring order, not the queryset's: the recruiter's own order is the
    only order the page can honestly claim."""
    hades = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    celeste = Game.objects.create(title="Celeste", source=Game.Source.MANUAL)

    rendered = str(RecruiterSearchForm({"games": [str(celeste.pk), str(hades.pk)]})["games"])

    assert rendered.index("Celeste") < rendered.index("Hades")


def test_unknown_game_id_renders_no_chip() -> None:
    """Same property the base class exists for: a label is never derived from
    the raw value, so a stale or invented id renders nothing at all."""
    rendered = str(RecruiterSearchForm({"games": ["424242"]})["games"])

    assert 'value="424242"' not in rendered


@pytest.mark.parametrize("junk", ["abc", "1;DROP", "-1", "²", "99999999999999999999"])
def test_junk_game_id_does_not_break_the_public_page(client: Client, junk: str) -> None:
    """The public page returns 200 for junk in `?games=`, exercising
    `_chips()` for real: `templates/search/people_search.html` renders
    `form["games"]` unconditionally, so this request reaches the widget with
    the raw, unclean value regardless of what `ModelMultipleChoiceField`'s own
    pk validation decides separately. That validation does reject the junk and
    the page renders with a field error too, but it runs in `full_clean()`,
    independent of `_chips()` reading the widget's raw data during render —
    without the guard this would still 500 rendering the field. That makes
    this the strongest guard against a 500 from a hand-typed URL, not a weak
    sibling of the widget-level test below: it goes through the real view, not
    the widget in isolation. See test_junk_game_id_is_filtered_before_the_query
    for the guard itself.

    The out-of-range value is here to pin the surprise rather than a fix:
    Postgres promotes the literal instead of overflowing, so `id IN (10^20)`
    simply matches nothing. Measured against the existing `engines` facet
    before this branch — all five shapes already returned 200 there."""
    response = client.get(reverse("home"), {"games": junk})

    assert response.status_code == 200


@pytest.mark.parametrize("junk", ["abc", "1;DROP", "²"])
def test_junk_game_id_is_filtered_before_the_query(junk: str) -> None:
    """The guard `_chips()` applies, pinned where it actually runs.

    `Game.objects.filter(pk__in=["abc"])` raises ValueError, so without the
    filter this render would raise rather than return markup. Every value here
    was mutation-checked against a guard-less `_chips()`; `"-1"` was dropped
    because it survives one (`int("-1")` doesn't raise, and no game has that
    pk), which would have made this docstring's claim false for a quarter of
    its own cases. `"²"` earns the `isascii()` half specifically: it is a digit
    to Python and not to `int()`.

    Driven through the widget directly rather than through an HTTP round-trip:
    `templates/search/people_search.html` renders `form["games"]` now, so
    test_junk_game_id_does_not_break_the_public_page above also exercises this
    guard end to end — but it only asserts a 200. This test isolates the guard
    and asserts on the markup, so a rewrite that stops filtering but happens
    to still 200 some other way would still be caught here.
    """
    rendered = str(RecruiterSearchForm({"games": [junk]})["games"])

    assert f'value="{junk}"' not in rendered


def test_chip_lookup_does_not_scale_with_the_catalogue(django_assert_num_queries: Any) -> None:
    """The regression this widget exists for. Two selected games must cost the
    same number of queries whether the catalogue holds 3 games or 391k — pinned
    by query count, so any rewrite that re-iterates self.choices fails here
    however it spells it."""
    picked = [Game.objects.create(title=f"Picked {n}", source=Game.Source.MANUAL) for n in range(2)]
    for n in range(20):
        Game.objects.create(title=f"Noise {n}", source=Game.Source.MANUAL)

    # 2, not 1: BoundField.build_widget_attrs reads self.errors to set
    # aria-invalid (Django >=5.2), which runs full_clean() and so
    # ModelMultipleChoiceField's own `pk__in` validation query — a query this
    # widget doesn't control and can't avoid. Still bounded by the selection,
    # not the catalogue: both queries filter on the 2 picked ids only, so the
    # invariant this test exists for — no per-Noise-row cost — still holds.
    with django_assert_num_queries(2):
        RecruiterSearchForm({"games": [str(g.pk) for g in picked]})["games"].as_widget()


def test_home_page_never_selects_the_full_game_table(client: Client) -> None:
    """The actual regression, caught where it actually happens — not on the
    bound path above.

    A query COUNT can't tell `GameTypeaheadSelectMultiple` from the base
    `TypeaheadSelectMultiple` on the bound path: the base class's
    `self.choices` iteration is itself one query there, so
    `django_assert_num_queries(2)` in the test above passes unchanged even
    with the guard deleted (verified by swapping the widget: all other tests
    stayed green too). The base class's real defect only shows on the
    UNBOUND path — `_chips()` builds its full `{value: label}` map
    unconditionally, even when nothing is selected — and the home page's
    default render (a bare `GET /`, no querystring) is exactly that: an
    unbound form. With the base widget it issues a second, unfiltered
    `SELECT` over every `games_game` row and column, summary included.

    So this asserts on SQL shape instead of a count: no query may select from
    `games_game` as its source table without a `WHERE ... IN` narrowing it to
    a selection. The `INNER JOIN` the "latest credits" feed makes into
    `games_game` doesn't trip this — only a query with `games_game` as the
    `FROM` table does, and today that only happens through `_chips()`.
    """
    with CaptureQueriesContext(connection) as queries:
        response = client.get(reverse("home"))

    assert response.status_code == 200
    for query in queries.captured_queries:
        sql = query["sql"]
        if 'FROM "games_game"' in sql:
            assert "WHERE" in sql and " IN (" in sql, sql

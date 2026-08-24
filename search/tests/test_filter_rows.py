"""The filter bento (spec 2026-08-24-filter-bento-and-game-facet-design §2):
the games section — split into two alternative sub-cards, criteria versus
named games — and the person row, every filter visible without scrolling on
a laptop."""

import html
import re

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _fieldsets(body: str) -> dict[str, str]:
    """Keyed on the legend text, unescaped: `{% translate %}` autoescapes, so
    "they've" reaches the HTML as "they&#x27;ve"."""
    return {
        html.unescape(re.search(r"<legend>([^<]+)</legend>", fs).group(1)).strip(): fs  # ty: ignore[unresolved-attribute]
        for fs in re.findall(r"<fieldset[^>]*>.*?</fieldset>", body, re.S)
    }


def test_two_rows_hold_the_right_filters(client: Client) -> None:
    body = client.get(reverse("home")).content.decode()
    rows = _fieldsets(body)
    assert set(rows) == {"The games they've worked on", "The person"}
    game, person = rows["The games they've worked on"], rows["The person"]
    for name in ("engines", "genres", "min_rating"):
        assert f'name="{name}"' in game or f'id="id_{name}"' in game
    for name in ("discipline", "countries", "year_from", "open_to_work"):
        assert f'name="{name}"' in person or f'id="id_{name}"' in person


def test_data_caveats_are_one_footnote(client: Client) -> None:
    body = client.get(reverse("home")).content.decode()
    main = body[body.index("<main") : body.index("</main>")]
    assert main.count("Steam-linked games only") == 1
    assert "Matches games using any of the selected." not in main


def test_empty_chips_list_renders_truly_empty(client: Client) -> None:
    """`.chips:empty { display:none }` is the hiding mechanism (app.css) — a
    lone whitespace text node defeats `:empty`, and the dead list's bottom
    margin pushed the four typeahead inputs 5px under their row neighbours
    (spec 2026-08-24 §3.1)."""
    content = client.get(reverse("home")).content.decode()
    assert content.count('<ul class="chips" data-chips></ul>') == 4


def test_game_criteria_are_ordered_genre_rating_engine(client: Client) -> None:
    """Genre is the coarsest facet a recruiter reaches for and comes first;
    engine is the specialist's and comes last (spec 2026-08-24 §3)."""
    body = client.get(reverse("home")).content.decode()
    row = _fieldsets(body)["The games they've worked on"]

    assert (
        row.index('id="id_genres"') < row.index('id="id_min_rating"') < row.index('id="id_engines"')
    )


def test_the_two_game_cards_are_alternatives(client: Client) -> None:
    """The three criteria and the named games are drawn as two cards with OR
    between them — the layout IS the rule clean() enforces (spec §2, §7).

    The split is asserted per side, not over the whole section: counting cards
    and headings across the fieldset would still pass with `games` sitting in
    the criteria card beside genres, which is the one arrangement the drawing
    exists to rule out.

    Split on the OR marker rather than by matching the card elements. A
    non-greedy `<div class="filter-group">.*?</div></div>` stops at the first
    cell's closing tags, not the card's, and silently hands back a fragment
    that satisfies every assertion below — which is how the first version of
    this test passed with `games` deliberately misplaced.
    """
    body = client.get(reverse("home")).content.decode()
    row = _fieldsets(body)["The games they've worked on"]
    criteria, _or, games = row.partition('class="filter-or"')

    assert row.count('class="filter-group"') == 2
    assert ">OR<" in row
    assert "Games matching all of:" in criteria
    assert 'id="id_genres"' in criteria and 'id="id_games"' not in criteria
    assert "Credited on any of:" in games
    assert 'id="id_games"' in games and 'id="id_genres"' not in games


def test_the_games_facet_is_not_in_the_person_row(client: Client) -> None:
    person = _fieldsets(client.get(reverse("home")).content.decode())["The person"]
    assert 'id="id_games"' not in person


def test_fields_are_named_in_plain_words(client: Client) -> None:
    """The old labels named the database column ("Engines", "Discipline"), not
    the question a visitor is answering (spec 2026-08-24 §5)."""
    body = client.get(reverse("home")).content.decode()

    for label in (
        "Game genre",
        "Minimum player rating (%)",
        "Game engine",
        "Specific games",
        "Their role",
        "Based in",
        "Credited since (year)",
    ):
        assert f">{label}</label>" in body, label
    assert ">Engines</label>" not in body
    assert ">Discipline</label>" not in body

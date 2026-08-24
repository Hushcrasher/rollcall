"""Two named filter rows (spec 2026-08-21-search-chrome §2): the game row and
the person row, every filter visible without scrolling on a laptop."""

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
    assert set(rows) == {"Games they worked on", "About the person"}
    game, person = rows["Games they worked on"], rows["About the person"]
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
    row = _fieldsets(body)["Games they worked on"]

    assert (
        row.index('id="id_genres"') < row.index('id="id_min_rating"') < row.index('id="id_engines"')
    )


def test_the_two_game_cards_are_alternatives(client: Client) -> None:
    """The three criteria and the named games are drawn as two cards with OR
    between them — the layout IS the rule clean() enforces (spec §2, §7)."""
    body = client.get(reverse("home")).content.decode()
    row = _fieldsets(body)["Games they worked on"]

    assert row.count('class="filter-group"') == 2
    assert "Games matching all of:" in row
    assert "Credited on any of:" in row
    assert ">OR<" in row
    assert 'id="id_games"' in row


def test_the_games_facet_is_not_in_the_person_row(client: Client) -> None:
    person = _fieldsets(client.get(reverse("home")).content.decode())["About the person"]
    assert 'id="id_games"' not in person

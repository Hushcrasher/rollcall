"""Typeahead behind the recruiter search's genres / games / engines / countries filters.

The filters used to be checkbox lists — one `<input>` per choice, 249 of them
for countries alone, on every anonymous hit. These cover the replacement: the
autocomplete endpoints, and the chips the widget renders back.
"""

import re
from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import translation

from games.models import Engine, EngineFamily, Game, Genre
from search.views import country_autocomplete

pytestmark = pytest.mark.django_db


# --- The endpoints ----------------------------------------------------------


def test_engine_autocomplete_returns_matching_options(client: Client) -> None:
    Engine.objects.create(name="Unreal Engine")
    Engine.objects.create(name="Unity")

    response = client.get(reverse("search:engine_autocomplete"), {"q": "unrea"})

    assert response.status_code == 200
    assert b"Unreal Engine" in response.content
    assert b"Unity" not in response.content


def test_genre_autocomplete_returns_matching_options(client: Client) -> None:
    Genre.objects.create(name="Roguelike")
    Genre.objects.create(name="Platformer")

    response = client.get(reverse("search:genre_autocomplete"), {"q": "rogue"})

    assert response.status_code == 200
    assert b"Roguelike" in response.content
    assert b"Platformer" not in response.content


def test_option_carries_the_value_the_form_expects(client: Client) -> None:
    """The option's data-id becomes a chip's hidden input, so it must be the pk
    the form's ModelMultipleChoiceField will resolve."""
    unreal = Engine.objects.create(name="Unreal Engine")
    response = client.get(reverse("search:engine_autocomplete"), {"q": "unreal"})
    assert f'data-id="{unreal.pk}"'.encode() in response.content


@pytest.mark.parametrize("url_name", ["search:engine_autocomplete", "search:genre_autocomplete"])
def test_reference_autocomplete_blank_query_is_empty(client: Client, url_name: str) -> None:
    Engine.objects.create(name="Unreal Engine")
    Genre.objects.create(name="Roguelike")

    response = client.get(reverse(url_name), {"q": "   "})

    assert response.status_code == 200
    assert b"autocomplete-option" not in response.content


def test_country_autocomplete_matches_by_name(client: Client) -> None:
    response = client.get(reverse("search:country_autocomplete"), {"q": "fra"})

    assert response.status_code == 200
    assert b'data-id="FR"' in response.content
    assert b"France" in response.content
    assert b'data-id="SE"' not in response.content


def test_country_autocomplete_blank_query_is_empty(client: Client) -> None:
    response = client.get(reverse("search:country_autocomplete"), {"q": ""})
    assert response.status_code == 200
    assert b"autocomplete-option" not in response.content


def test_country_autocomplete_matches_the_translated_name() -> None:
    """Typing "allem" must find Allemagne under `fr` — searching the English
    names would strand every non-English user.

    Driven through the view directly, under an explicit override: LANGUAGES is
    en-only, so LocaleMiddleware would pin a `client` request back to English.
    """
    request = RequestFactory().get("/", {"q": "allem"})

    with translation.override("fr"):
        response = country_autocomplete(request)

    assert b'data-id="DE"' in response.content
    assert b"Allemagne" in response.content


def test_country_autocomplete_touches_no_database(
    client: Client, django_assert_num_queries: Any
) -> None:
    """django-countries keeps the list in memory — 249 rows the DB never sees."""
    with django_assert_num_queries(0):
        client.get(reverse("search:country_autocomplete"), {"q": "fra"})


def test_game_filter_autocomplete_returns_matching_options(client: Client) -> None:
    Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    Game.objects.create(title="Celeste", source=Game.Source.MANUAL)

    response = client.get(reverse("search:game_filter_autocomplete"), {"q": "hade"})

    assert response.status_code == 200
    assert b"Hades" in response.content
    assert b"Celeste" not in response.content


def test_game_filter_option_carries_the_pk(client: Client) -> None:
    hades = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    response = client.get(reverse("search:game_filter_autocomplete"), {"q": "hades"})
    assert f'data-id="{hades.pk}"'.encode() in response.content


def test_game_filter_autocomplete_offers_no_deeper_search(client: Client) -> None:
    """Deliberately NOT search:game_autocomplete, which offers the IGDB import:
    importing a game nobody is credited on cannot make this filter match a
    single person, and it would spend an IGDB call and the owner's per-IP quota
    to add an option guaranteed to return zero results (spec 2026-08-24 §6)."""
    response = client.get(reverse("search:game_filter_autocomplete"), {"q": "nothing here"})

    assert response.status_code == 200
    assert b"igdb-trigger" not in response.content
    assert b"deeper search" not in response.content


def test_game_filter_autocomplete_blank_query_is_empty(client: Client) -> None:
    Game.objects.create(title="Hades", source=Game.Source.MANUAL)

    response = client.get(reverse("search:game_filter_autocomplete"), {"q": "   "})

    assert response.status_code == 200
    assert b"autocomplete-option" not in response.content


@pytest.mark.parametrize(
    "url_name",
    [
        "search:engine_autocomplete",
        "search:genre_autocomplete",
        "search:country_autocomplete",
        "search:game_filter_autocomplete",
    ],
)
def test_filter_autocomplete_is_rate_limited(client: Client, settings: Any, url_name: str) -> None:
    """Public endpoints, so the same IP limit as the search pages they serve."""
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    url = reverse(url_name)
    assert client.get(url, {"q": "a"}).status_code == 200
    assert client.get(url, {"q": "a"}).status_code == 403


# --- The engine facet's mixed list ------------------------------------------


def _unity_family() -> EngineFamily:
    family = EngineFamily.objects.create(name="Unity")
    Engine.objects.create(name="Unity", family=family)
    Engine.objects.create(name="Unity 2021", family=family)
    return family


def test_engine_autocomplete_puts_the_family_before_its_members(client: Client) -> None:
    """The head is the pick worth making — it reaches every spelling — so it
    must not be pushed under the versions it stands for."""
    _unity_family()

    content = client.get(reverse("search:engine_autocomplete"), {"q": "unity"}).content.decode()

    assert content.index('data-param="engine_families"') < content.index('data-param="engines"')


def test_engine_autocomplete_tags_each_option_with_its_field(client: Client) -> None:
    """A chip's hidden input has to be named for the field that will clean it,
    and the two kinds post to different fields — without this the client has no
    way to tell a family pick from a version pick."""
    family = _unity_family()

    content = client.get(reverse("search:engine_autocomplete"), {"q": "unity"}).content.decode()

    assert f'data-param="engine_families" data-id="{family.pk}"' in content
    version = Engine.objects.get(name="Unity 2021")
    assert f'data-param="engines" data-id="{version.pk}"' in content


def test_engine_autocomplete_offers_the_family_when_only_a_member_matches(
    client: Client,
) -> None:
    """Typing "2021" should still let a recruiter take all of Unity — that is
    the broader pick, and the more likely intent."""
    family = _unity_family()

    content = client.get(reverse("search:engine_autocomplete"), {"q": "2021"}).content.decode()

    assert f'data-param="engine_families" data-id="{family.pk}"' in content


def test_engine_autocomplete_indents_members_and_not_heads(client: Client) -> None:
    """The indent IS the relationship; a head rendered as a child would read as
    a version of itself.

    Note the engine row literally named "Unity" is a MEMBER of the Unity family
    and indents like any other — the head above it is the family, a different
    thing that happens to share the name. Asserted per option rather than by
    counting, which was how the first version of this test got it wrong.
    """
    _unity_family()

    content = client.get(reverse("search:engine_autocomplete"), {"q": "unity"}).content.decode()
    options = re.findall(r'<button[^>]*data-param="([a-z_]+)"[^>]*>', content)
    classes = re.findall(r'class="(autocomplete-option[^"]*)"', content)

    assert options[0] == "engine_families"
    assert "autocomplete-child" not in classes[0]
    assert all("autocomplete-child" in c for c in classes[1:])
    assert all(p == "engines" for p in options[1:])


def test_an_engine_with_no_family_stays_a_plain_option(client: Client) -> None:
    """~1,200 engines belong to no family and must behave as they always have."""
    loose = Engine.objects.create(name="PICO-8")

    content = client.get(reverse("search:engine_autocomplete"), {"q": "pico"}).content.decode()

    assert f'data-param="engines" data-id="{loose.pk}"' in content
    assert "autocomplete-child" not in content
    assert "engine_families" not in content


def test_engine_autocomplete_blank_query_is_empty(client: Client) -> None:
    _unity_family()

    response = client.get(reverse("search:engine_autocomplete"), {"q": "   "})

    assert response.status_code == 200
    assert b"autocomplete-option" not in response.content


@pytest.mark.parametrize("junk", ["abc", "1;DROP", "-1", "99999999999999999999"])
def test_junk_engine_family_id_does_not_break_the_public_page(client: Client, junk: str) -> None:
    """Same guard as the games facet: the chips are rendered from the raw
    querystring during render, before field validation has had its say."""
    response = client.get(reverse("home"), {"engine_families": junk})

    assert response.status_code == 200


def test_selected_family_renders_as_a_chip(client: Client) -> None:
    family = _unity_family()

    content = _search(client, f"?engine_families={family.pk}")

    assert f'<input type="hidden" name="engine_families" value="{family.pk}">' in content
    assert "Unity" in content


# --- The widget -------------------------------------------------------------


def _search(client: Client, query: str) -> str:
    return client.get(reverse("home") + query).content.decode()


def test_empty_form_does_not_ship_a_choice_per_country(client: Client) -> None:
    """The regression this whole task exists for: the 249-country checkbox list.

    Pinned by payload, not by markup — any rewrite that re-inlines the choices
    fails here however it spells them.

    Caps re-measured for the fourth (games) typeahead added in Task 5: the
    empty home page carries 12 `<input>` tags and 10,021 bytes (measured via
    this same client/route, empty test db — not the dev server, whose local
    Postgres has seeded "Latest credits" rows that inflate byte count for
    reasons unrelated to the filters). Caps sit at roughly twice those values,
    not just above them: the regression this guards against costs 253 inputs
    and 39,234 bytes, so anything under ~24/20k catches it just as decisively,
    while a cap two inputs above the measurement would fail on the next
    legitimate filter and teach whoever hits it to raise the number rather
    than ask why it moved.
    """
    content = _search(client, "")

    assert "France" not in content  # no country is named on the empty form
    assert content.count("<input") < 24  # measured 12; 249 choices would be 253
    assert len(content) < 20_000  # measured 10,021 bytes; the old list was 39,234


def test_selected_values_render_as_chips(client: Client) -> None:
    unreal = Engine.objects.create(name="Unreal Engine")

    content = _search(client, f"?countries=FR&engines={unreal.pk}")

    assert '<input type="hidden" name="countries" value="FR">' in content
    assert "France" in content
    assert f'<input type="hidden" name="engines" value="{unreal.pk}">' in content
    assert "Unreal Engine" in content


def test_chips_are_ordered_as_given(client: Client) -> None:
    content = _search(client, "?countries=SE&countries=FR")
    assert content.index("Sweden") < content.index("France")


def test_chip_remove_control_names_its_value(client: Client) -> None:
    """ "×" alone is not an accessible name — three chips would all read "×"."""
    content = _search(client, "?countries=FR")
    assert 'aria-label="Remove France"' in content


def test_typeahead_input_has_a_real_label(client: Client) -> None:
    """The countries control sits inside a <fieldset><legend> (the "The person"
    row, spec 2026-08-24-filter-bento-and-game-facet-design §5), but that legend only names
    the GROUP — countries keeps its own <label for>, unlike the old checkbox
    list where the legend was the only accessible name 249 checkboxes shared.
    No more aria-describedby: the per-field help text that used to attach here
    is gone, folded into the page's single data-caveat footnote. Scoped to the
    countries <input> itself, not the whole page — other markup gaining an
    aria-describedby elsewhere shouldn't fail this test."""
    content = _search(client, "")

    assert '<label for="id_countries">' in content
    tag = re.search(r'<input[^>]*id="id_countries"[^>]*>', content)
    assert tag, 'no <input id="id_countries"> tag found'
    assert "aria-describedby" not in tag.group(0)
    assert "<legend>" in content


def test_unknown_country_code_renders_no_chip(client: Client) -> None:
    """`Country("ZZ")` is truthy but its `.name` is "" — deriving the label from
    the code instead of the choices would render a blank, nameless chip."""
    content = _search(client, "?countries=ZZ")

    assert 'value="ZZ"' not in content
    assert "Select a valid choice" in content


def test_chip_labels_follow_the_active_language() -> None:
    """Same reason the choices are a callable (Task 5) — don't regress it."""
    from search.forms import RecruiterSearchForm

    with translation.override("fr"):
        rendered = str(RecruiterSearchForm({"countries": ["DE"]})["countries"])

    assert "Allemagne" in rendered


def test_typeahead_search_box_stays_out_of_the_querystring(client: Client) -> None:
    """The box is named `q` for htmx, but owned by an empty scratch form — four
    boxes submitting `?q=&q=&q=&q=` would ride along in every shareable and
    paginated URL."""
    content = _search(client, "")

    assert '<form id="typeahead-scratch" hidden></form>' in content
    assert content.count('form="typeahead-scratch"') == 4


def test_no_js_hides_the_dead_controls_and_says_so(client: Client) -> None:
    """Accepted limitation, not graceful degradation: the typeahead is htmx. So
    the search box and remove buttons are hidden rather than left inert, and the
    page names what still works."""
    content = _search(client, "")

    assert "<noscript>" in content
    assert ".js-only { display: none; }" in content
    assert "need JavaScript" in content
    assert content.count('class="autocomplete-input js-only"') == 4

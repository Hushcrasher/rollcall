"""Typeahead behind the recruiter search's engines / genres / countries filters.

The filters used to be checkbox lists — one `<input>` per choice, 249 of them
for countries alone, on every anonymous hit. These cover the replacement: the
autocomplete endpoints, and the chips the widget renders back.
"""

from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import translation

from games.models import Engine, Genre
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


@pytest.mark.parametrize(
    "url_name",
    [
        "search:engine_autocomplete",
        "search:genre_autocomplete",
        "search:country_autocomplete",
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


# --- The widget -------------------------------------------------------------


def _search(client: Client, query: str) -> str:
    return client.get(reverse("search:recruiter_search") + query).content.decode()


def test_empty_form_does_not_ship_a_choice_per_country(client: Client) -> None:
    """The regression this whole task exists for: the 249-country checkbox list.

    Pinned by payload, not by markup — any rewrite that re-inlines the choices
    fails here however it spells them.
    """
    content = _search(client, "")

    assert "France" not in content  # no country is named on the empty form
    assert content.count("<input") < 20  # was 253
    assert len(content) < 15_000  # was 39,234 bytes


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
    """A <legend> is the accessible name of *every* control in its fieldset —
    which is how the old list announced its help text 249 times. One label, one
    input, and the help text attached once via aria-describedby."""
    content = _search(client, "")

    assert '<label for="id_countries">' in content
    assert 'id="id_countries"' in content
    assert 'aria-describedby="id_countries_helptext"' in content
    assert 'id="id_countries_helptext"' in content
    assert "<legend>" not in content


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
    """The box is named `q` for htmx, but owned by an empty scratch form — three
    boxes submitting `?q=&q=&q=` would ride along in every shareable and
    paginated URL."""
    content = _search(client, "")

    assert '<form id="typeahead-scratch" hidden></form>' in content
    assert content.count('form="typeahead-scratch"') == 3


def test_no_js_hides_the_dead_controls_and_says_so(client: Client) -> None:
    """Accepted limitation, not graceful degradation: the typeahead is htmx. So
    the search box and remove buttons are hidden rather than left inert, and the
    page names what still works."""
    content = _search(client, "")

    assert "<noscript>" in content
    assert ".js-only { display: none; }" in content
    assert "need JavaScript" in content
    assert content.count('class="autocomplete-input js-only"') == 3

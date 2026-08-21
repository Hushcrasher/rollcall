"""The nav search box — sitewide chrome in base.html, backed by search:suggest."""

import pytest
from django.test import Client
from django.urls import reverse

from conftest import header as _header

pytestmark = pytest.mark.django_db


def test_the_placeholder_names_all_three_things_it_matches(client: Client) -> None:
    """`suggest()` returns games, people AND companies; "Search…" said none of
    it, and the box is the only route to game/company lookup now."""
    header = _header(client.get(reverse("home")).content.decode())
    assert "Search games, companies and people" in header


def test_the_box_relies_on_css_not_a_hardcoded_width(client: Client) -> None:
    """.nav-search sizes the input via flex (app.css); a fixed `size`
    attribute would fight that layout on narrow viewports, so the markup
    just needs the input and its placeholder, not a hardcoded width."""
    header = _header(client.get(reverse("home")).content.decode())
    assert 'placeholder="Search games, companies and people"' in header
    assert "size=" not in header

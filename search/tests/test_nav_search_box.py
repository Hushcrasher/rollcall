"""The nav search box — sitewide chrome in base.html, backed by search:suggest."""

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_the_placeholder_names_all_three_things_it_matches(client: Client) -> None:
    """`suggest()` returns games, people AND companies; "Search…" said none of
    it, and the box is the only route to game/company lookup now."""
    body = client.get(reverse("home")).content
    assert b"Search games, companies and people" in body


def test_the_box_is_wide_enough_for_its_placeholder(client: Client) -> None:
    """Without a declared width the input falls to the browser default of about
    20 characters and truncates the label — which would make the fix above
    invisible, the exact failure it exists to correct."""
    body = client.get(reverse("home")).content
    assert b'size="35"' in body

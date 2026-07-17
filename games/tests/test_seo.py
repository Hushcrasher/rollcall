"""robots.txt + sitemap — index public pages (SEO), exclude private profiles."""

from urllib.robotparser import RobotFileParser

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from games.models import Game

pytestmark = pytest.mark.django_db


def test_robots_txt_allows_indexing_and_points_to_sitemap(client: Client) -> None:
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    body = response.content
    assert b"Sitemap:" in body
    assert b"Disallow: /admin/" in body
    assert b"Disallow: /settings/" in body


def test_robots_txt_opens_the_promise_page_but_not_the_filter_search(client: Client) -> None:
    """The "For recruiters" landing page lives *under* the disallowed `/search/`
    prefix, so its indexability rests entirely on Allow/Disallow precedence.

    Asserted by parsing the response with a real robots parser rather than
    grepping for the `Allow:` line: the line being present proves nothing —
    emitted *after* `Disallow: /search/` it is silently inert under first-match
    parsers (verified: `urllib.robotparser` denies the page in that order).
    This fails if the rule is dropped OR merely reordered.

    `/search/recruiters/` must stay denied: a combinatorial filter-URL space is
    a crawl trap that the IP rate limit would only fight.
    """
    body = client.get("/robots.txt").content.decode()

    parser = RobotFileParser()
    parser.parse(body.splitlines())

    assert parser.can_fetch("*", "/search/for-recruiters/")
    assert not parser.can_fetch("*", "/search/recruiters/")
    assert not parser.can_fetch("*", "/search/")
    assert parser.can_fetch("*", "/u/someone/")  # public profiles still indexable


def test_sitemap_lists_public_profiles_and_games(client: Client) -> None:
    public = User.objects.create_user(email="pub@example.com", password="x", display_name="Pub")
    private = User.objects.create_user(
        email="priv@example.com", password="x", display_name="Priv", profile_public=False
    )
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)

    response = client.get(reverse("sitemap"))

    assert response.status_code == 200
    body = response.content
    assert public.get_absolute_url().encode() in body
    assert private.get_absolute_url().encode() not in body  # private excluded
    assert game.get_absolute_url().encode() in body


def test_game_and_company_have_absolute_urls() -> None:
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    assert game.get_absolute_url() == f"/g/{game.slug}/"

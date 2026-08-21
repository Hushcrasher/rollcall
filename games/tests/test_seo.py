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
    assert b"Disallow: /account/" in body
    assert b"Disallow: /profile/" in body


def test_robots_txt_keeps_content_pages_and_denies_private_areas(client: Client) -> None:
    """Asserted by parsing the response with a real robots parser rather than
    grepping for the lines, so a rule that is present but does not actually
    grant/deny the paths it should still fails the test. This fails if a rule
    is dropped.

    The page-prefix rules asserted here don't depend on emission order — no
    `Disallow` prefix overlaps `/u/`, `/g/` or `/c/`. The card rules do, and
    are covered by the wildcard test below, which this parser cannot express.
    """
    body = client.get("/robots.txt").content.decode()

    parser = RobotFileParser()
    parser.parse(body.splitlines())

    assert parser.can_fetch("*", "/u/someone/")  # public profiles are the SEO channel
    assert parser.can_fetch("*", "/g/some-game/")
    assert parser.can_fetch("*", "/c/some-studio/")
    assert not parser.can_fetch("*", "/search/")
    assert not parser.can_fetch("*", "/account/")
    # No carve-out survives the promise page it was written for.
    assert not parser.can_fetch("*", "/search/for-recruiters/")
    # A POST-driven entry point with nothing crawlable behind it, and its page
    # duplicates the home page's <h1>/<title> verbatim.
    assert not parser.can_fetch("*", "/declare/")


def test_robots_txt_closes_the_root_filter_trap(client: Client) -> None:
    """The people search is the home page, so `/` must stay crawlable while
    `/?discipline=3&engines=5&page=2` must not.

    Asserted on the literal line and NOT through `RobotFileParser`: Python's
    parser ignores wildcards and would read `/*?` as a literal prefix matching
    nothing, so it cannot express this rule either way. Google and Bing do
    implement RFC 9309 §2.2.3 wildcards, and they are the crawlers whose budget
    the trap would burn. Coverage is deliberately partial; the root template's
    rel=canonical is the second layer.
    """
    body = client.get("/robots.txt").content.decode()

    assert "Disallow: /*?" in body

    parser = RobotFileParser()
    parser.parse(body.splitlines())
    assert parser.can_fetch("*", "/")  # the home page itself stays indexable


def test_robots_txt_keeps_the_og_card_urls_out_of_the_filter_trap(client: Client) -> None:
    """Every `og:image` URL carries `?v=<token>`, so `Disallow: /*?` matches it
    for the wildcard-aware crawlers. The three card patterns must be present
    AND longer than `/*?` (RFC 9309 §2.2.2 longest match) AND emitted first
    (first-match parsers), or a card is a blocked, silently broken preview.

    Asserted on the literal lines: `RobotFileParser` ignores wildcards, so it
    cannot express `/*?` or `/u/*/card.png` either way.
    """
    lines = client.get("/robots.txt").content.decode().splitlines()
    trap = "Disallow: /*?"

    for path in ("/card.png", "/u/*/card.png", "/g/*/card.png"):
        line = f"Allow: {path}"
        assert line in lines
        assert len(path) > len("/*?")  # longest match wins
        assert lines.index(line) < lines.index(trap)  # first match wins


def test_the_home_page_declares_itself_canonical(client: Client) -> None:
    """Filtered result pages are not distinct content. robots.txt stops the
    crawl; this collapses any variant reached from an external link anyway."""
    body = client.get(reverse("home")).content.decode()
    assert '<link rel="canonical" href="/">' in body


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

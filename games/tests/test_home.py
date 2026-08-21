"""The home page IS the people search (spec docs/superpowers/specs/
2026-08-11-home-is-people-search-design.md). It used to be a menu of four links
that were all reachable from the nav bar anyway."""

from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db

PITCH = b"Worked on a game?"

_TEMPLATE = Path(settings.BASE_DIR) / "templates" / "search" / "people_search.html"


def test_home_is_public_and_renders_the_search_form(client: Client) -> None:
    response = client.get(reverse("home"))
    assert response.status_code == 200
    # Filters-first (spec 2026-08-20): one H1 for everyone, the tool under it.
    assert b"Find people by what they" in response.content
    assert b"discipline" in response.content.lower()


def test_home_banner_invites_an_anonymous_visitor_to_declare(client: Client) -> None:
    """Success metric #1 is workers declaring their work. The funnel moved to
    /declare/; the home keeps a one-line banner. Scoped to <main> — the nav
    CTA satisfies a looser assertion."""
    body = client.get(reverse("home")).content.decode()
    main = body[body.index("<main") : body.index("</main>")]
    assert "Worked on a game?" in main
    assert reverse("contributions:declare") in main


def test_the_banner_has_no_trailing_qualifier_clause() -> None:
    """The banner used to be one sentence fragmented around a link ("Worked on
    a game? Add your credit — no account needed to start.") — that clause is
    gone (spec 2026-08-21-search-chrome §3), so the two remaining phrases are
    each a complete unit on their own and no longer need a single
    {% blocktranslate %} to keep a shared sentence from being reordered."""
    source = _TEMPLATE.read_text()
    assert '{% translate "Worked on a game?" %}' in source
    assert "no account needed to start" not in source


def test_a_member_gets_the_tool_without_the_pitch(client: Client) -> None:
    """They already have an account — the pitch is spent."""
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)
    response = client.get(reverse("home"))
    assert PITCH not in response.content
    assert b"discipline" in response.content.lower()  # the tool is still there

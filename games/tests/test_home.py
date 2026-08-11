"""The home page IS the people search (spec docs/superpowers/specs/
2026-08-11-home-is-people-search-design.md). It used to be a menu of four links
that were all reachable from the nav bar anyway."""

import re

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db

PITCH = b"credits database for the video game industry"


def test_home_is_public_and_renders_the_search_form(client: Client) -> None:
    response = client.get(reverse("home"))
    assert response.status_code == 200
    # Substring stops before the apostrophe in "they've": how a template engine
    # renders that entity is not what this test is about.
    assert b"Find people by what they" in response.content
    assert b"discipline" in response.content.lower()


def test_home_pitches_signup_to_an_anonymous_visitor(client: Client) -> None:
    """Success metric #1 is workers signing up. With the "For recruiters" page
    gone, this line is the only surviving statement of the recruiter promise
    that docs/01-DESIGN.md §3.6 calls load-bearing for worker motivation."""
    response = client.get(reverse("home"))
    assert PITCH in response.content
    # Scoped to the pitch <p> itself, not "anywhere on the page": base.html's
    # nav also carries a permanent "Sign up" link, so an unscoped check would
    # stay green even if the CTA were deleted from the pitch paragraph.
    match = re.search(
        rb"<p>(?:(?!</p>).)*?" + PITCH + rb"(?:(?!</p>).)*?</p>", response.content, re.DOTALL
    )
    assert match is not None, f"no pitch <p> found in:\n{response.content[-3000:]}"
    assert reverse("accounts:signup").encode() in match.group(0)


def test_a_member_gets_the_tool_without_the_pitch(client: Client) -> None:
    """They already have an account — the pitch is spent."""
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)
    response = client.get(reverse("home"))
    assert PITCH not in response.content
    assert b"discipline" in response.content.lower()  # the tool is still there

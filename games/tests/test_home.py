"""The home page IS the people search (spec docs/superpowers/specs/
2026-08-11-home-is-people-search-design.md). It used to be a menu of four links
that were all reachable from the nav bar anyway."""

import re

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db

PITCH = b"Add a credit to your name"


def test_home_is_public_and_renders_the_search_form(client: Client) -> None:
    response = client.get(reverse("home"))
    assert response.status_code == 200
    # The anonymous <h1> is now the declare question (covered by its own test
    # below) — this just pins that the search form still renders, one heading
    # down under "Looking for someone?".
    assert b"Looking for someone?" in response.content
    assert b"discipline" in response.content.lower()


def test_home_invites_an_anonymous_visitor_to_declare(client: Client) -> None:
    """Success metric #1 is workers declaring their work. The question is the
    invitation, and it is scoped to the block that carries it — base.html's nav
    would satisfy a looser assertion."""
    body = client.get(reverse("home")).content.decode()
    assert "Which game did you work on?" in body
    match = re.search(r"<form[^>]*action=\"/declare/\"[^>]*>.*?</form>", body, re.S)
    assert match is not None, "no form posting to /declare/ on the home page"
    assert 'name="q"' in match.group(0)


def test_a_member_gets_the_tool_without_the_pitch(client: Client) -> None:
    """They already have an account — the pitch is spent."""
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)
    response = client.get(reverse("home"))
    assert PITCH not in response.content
    assert b"discipline" in response.content.lower()  # the tool is still there

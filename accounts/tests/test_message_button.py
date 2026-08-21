"""`Message` button replaces the `Contact` link on the profile and on search
result cards (docs/superpowers/specs/2026-08-21-search-chrome-design.md §4)."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_visitor_sees_a_message_button(client: Client) -> None:
    target = User.objects.create_user(email="t@example.com", password="x", display_name="Target")
    other = User.objects.create_user(email="o@example.com", password="x", display_name="Other")
    client.force_login(other)
    body = client.get(reverse("accounts:profile", args=[target.slug])).content.decode()
    main = body[body.index("<main") : body.index("</main>")]
    contact_url = reverse("contact:contact", args=[target.slug])
    assert f'<a role="button" href="{contact_url}">Message</a>' in main
    assert ">Contact<" not in main


def test_banner_has_no_trailing_clause(client: Client) -> None:
    body = client.get(reverse("home")).content.decode()
    assert "Worked on a game?" in body
    assert "no account needed to start" not in body

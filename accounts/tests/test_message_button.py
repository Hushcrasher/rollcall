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


def test_anonymous_visitor_sees_a_message_button(client: Client) -> None:
    """Spec 2026-08-24 §2: the profile is the recruiter's landing surface,
    so the contact action must be discoverable logged-out — the relay's own
    login + verified-email gates still guard the actual send."""
    target = User.objects.create_user(email="t@example.com", password="x", display_name="Target")
    body = client.get(reverse("accounts:profile", args=[target.slug])).content.decode()
    main = body[body.index("<main") : body.index("</main>")]
    contact_url = reverse("contact:contact", args=[target.slug])
    assert f'<a role="button" href="{contact_url}">Message</a>' in main


def test_owner_sees_no_message_button(client: Client) -> None:
    target = User.objects.create_user(email="t@example.com", password="x", display_name="Target")
    client.force_login(target)
    body = client.get(reverse("accounts:profile", args=[target.slug])).content.decode()
    main = body[body.index("<main") : body.index("</main>")]
    assert reverse("contact:contact", args=[target.slug]) not in main


def test_uncontactable_profile_shows_no_message_button(client: Client) -> None:
    target = User.objects.create_user(email="t@example.com", password="x", display_name="Target")
    target.contactable = False  # ty: ignore[invalid-assignment]
    target.save(update_fields=["contactable"])
    body = client.get(reverse("accounts:profile", args=[target.slug])).content.decode()
    main = body[body.index("<main") : body.index("</main>")]
    assert reverse("contact:contact", args=[target.slug]) not in main
    assert ">Message<" not in main

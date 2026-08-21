"""Opt-in public contact email (spec 2026-08-21-public-contact-email): a
SEPARATE address the member chooses to publish. The account email stays
private — every existing "no email" test keeps asserting that."""

from datetime import date
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from accounts.forms import ProfileForm
from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


def _user(**kw: Any) -> User:
    email = kw.pop("email", "login@example.com")
    return User.objects.create_user(email=email, password="x", display_name="Member", **kw)


def test_settings_form_saves_the_address_lowercased() -> None:
    user = _user()
    form = ProfileForm(
        data={"display_name": "Member", "public_email": "Hello@Studio.GG"}, instance=user
    )
    assert form.is_valid(), form.errors
    form.save()
    user.refresh_from_db()
    assert user.public_email == "hello@studio.gg"


def test_public_email_is_optional_and_independent_from_the_login_email() -> None:
    user = _user()
    form = ProfileForm(data={"display_name": "Member"}, instance=user)
    assert form.is_valid(), form.errors
    form.save()
    user.refresh_from_db()
    assert user.public_email == ""
    assert user.email == "login@example.com"


def test_settings_page_renders_the_field_with_its_help(client: Client) -> None:
    user = _user()
    client.force_login(user)
    body = client.get(reverse("accounts:profile_edit")).content.decode()
    assert 'name="public_email"' in body
    assert "Shown on your public profile to anyone" in body


def test_settings_form_rejects_a_malformed_address() -> None:
    user = _user()
    form = ProfileForm(
        data={"display_name": "Member", "public_email": "not-an-email"}, instance=user
    )
    assert not form.is_valid()
    assert "public_email" in form.errors


def _with_public_email() -> User:
    return _user(public_email="hello@studio.gg")


def test_public_profile_shows_the_mailto_to_anonymous_and_members(client: Client) -> None:
    user = _with_public_email()
    url = reverse("accounts:profile", args=[user.slug])
    assert 'href="mailto:hello@studio.gg"' in client.get(url).content.decode()
    other = _user(email="o@example.com")
    client.force_login(other)
    assert 'href="mailto:hello@studio.gg"' in client.get(url).content.decode()


def test_owner_sees_the_address_flagged_as_public(client: Client) -> None:
    user = _with_public_email()
    client.force_login(user)
    body = client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    assert "hello@studio.gg" in body and "Shown publicly" in body


def test_private_profile_still_404s_for_visitors(client: Client) -> None:
    user = _with_public_email()
    user.profile_public = False  # ty: ignore[invalid-assignment]
    user.save(update_fields=["profile_public"])
    assert client.get(reverse("accounts:profile", args=[user.slug])).status_code == 404


def test_the_address_appears_nowhere_else(client: Client) -> None:
    """Spec §4: public profile page only."""
    user = _with_public_email()
    game = Game.objects.create(title="Game", source=Game.Source.MANUAL)
    Contribution.objects.create(
        user=user,
        game=game,
        discipline=Discipline.objects.get(name="Design"),
        job_title="Dev",
        start_date=date(2020, 1, 1),
    )
    design = Discipline.objects.get(name="Design")
    pages = [
        reverse("home"),  # feed
        reverse("home") + f"?discipline={design.pk}",  # search results
        reverse("games:game", args=[game.slug]),
        reverse("cards:profile", args=[user.slug]),  # PNG bytes
    ]
    for url in pages:
        assert b"hello@studio.gg" not in client.get(url).content, url
    # The meta tags of the profile page itself.
    import re

    body = client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    for content in re.findall(r'<meta [^>]*content="([^"]*)"', body):
        assert "hello@studio.gg" not in content


def test_export_includes_the_public_email(client: Client) -> None:
    user = _with_public_email()
    client.force_login(user)
    assert (
        client.get(reverse("accounts:export_data")).json()["identity"]["public_email"]
        == "hello@studio.gg"
    )

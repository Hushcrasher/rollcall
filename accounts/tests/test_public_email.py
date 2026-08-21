"""Opt-in public contact email (spec 2026-08-21-public-contact-email): a
SEPARATE address the member chooses to publish. The account email stays
private — every existing "no email" test keeps asserting that."""

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from accounts.forms import ProfileForm
from accounts.models import User

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

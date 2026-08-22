"""Opt-in public contact email (spec 2026-08-21-public-contact-email): a
SEPARATE address the member chooses to publish. The account email stays
private — every existing "no email" test keeps asserting that."""

import re
from datetime import date
from typing import Any

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.forms import ProfileForm
from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Company, Game

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
    assert "whether or not relay contact is allowed" in body


def test_settings_form_rejects_a_malformed_address() -> None:
    user = _user()
    form = ProfileForm(
        data={"display_name": "Member", "public_email": "not-an-email"}, instance=user
    )
    assert not form.is_valid()
    assert "public_email" in form.errors


def test_admin_change_form_casefolds_the_public_email(client: Client) -> None:
    # Same case-folding rule as everywhere else (SignupForm.clean_email,
    # ProfileForm.clean_public_email) — staff posting through the admin must
    # not open a second, unfolded write path onto the same column.
    staff = User.objects.create_superuser(
        email="root@example.com", password="x", display_name="Root"
    )
    member = _user(email="member@example.com")
    client.force_login(staff)
    response = client.post(
        reverse("admin:accounts_user_change", args=[member.pk]),
        {
            "email": member.email,
            "display_name": member.display_name,
            "role": User.Role.MEMBER,
            "profile_public": "on",
            "contactable": "on",
            "is_active": "on",
            "public_email": "MiXeD@Studio.GG",
        },
    )
    assert response.status_code == 302  # a form error would render 200
    member.refresh_from_db()
    assert member.public_email == "mixed@studio.gg"


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


def test_owner_of_a_private_profile_sees_the_address_but_not_the_note(client: Client) -> None:
    # "Shown publicly" would be false: a private profile is 404 for everyone
    # but its owner, so the address the owner sees is not actually public.
    user = _with_public_email()
    user.profile_public = False  # ty: ignore[invalid-assignment]
    user.save(update_fields=["profile_public"])
    client.force_login(user)
    body = client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    assert "hello@studio.gg" in body
    assert "Shown publicly" not in body


def test_the_address_appears_nowhere_else(client: Client) -> None:
    """Spec §4: public profile page only."""
    user = _with_public_email()
    company = Company.objects.create(name="Employer Co", source=Company.Source.MANUAL)
    game = Game.objects.create(title="Game", source=Game.Source.MANUAL)
    Contribution.objects.create(
        user=user,
        game=game,
        company=company,
        discipline=Discipline.objects.get(name="Design"),
        job_title="Dev",
        start_date=date(2020, 1, 1),
    )
    design = Discipline.objects.get(name="Design")
    pages = [
        reverse("home"),  # feed
        reverse("home") + f"?discipline={design.pk}",  # search results
        reverse("games:game", args=[game.slug]),
        reverse("games:company", args=[company.slug]),
        reverse("sitemap"),
        # PNG bytes: the real guard is cards/data.py's CardData field list (no
        # email field exists to serialize) — a byte-absence check on rendered
        # pixels can catch a regression but can never prove the negative.
        reverse("cards:profile", args=[user.slug]),
    ]
    for url in pages:
        assert b"hello@studio.gg" not in client.get(url).content, url
    # The meta tags of the profile page itself.
    body = client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    for content in re.findall(r'<meta [^>]*content="([^"]*)"', body):
        assert "hello@studio.gg" not in content

    # The contact relay delivers to the ACCOUNT email (never rendered) and
    # never touches the public one — assert it end to end, not just by
    # inspecting the view (contact/tests/test_relay.py's POST idiom).
    sender = _user(email="sender@example.com", email_verified_at=timezone.now())
    client.force_login(sender)
    client.post(
        reverse("contact:contact", kwargs={"slug": user.slug}),
        {"subject": "Hi", "message": "Hello there."},
    )
    sent = mail.outbox[0]
    assert "hello@studio.gg" not in sent.body
    assert "hello@studio.gg" not in sent.to
    assert "hello@studio.gg" not in sent.reply_to
    assert "hello@studio.gg" not in str(sent.extra_headers)


def test_export_includes_the_public_email(client: Client) -> None:
    user = _with_public_email()
    client.force_login(user)
    assert (
        client.get(reverse("accounts:export_data")).json()["identity"]["public_email"]
        == "hello@studio.gg"
    )

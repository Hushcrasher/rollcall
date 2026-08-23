"""'View as member' — the owner previews their own profile as a logged-in
member sees it (docs/superpowers/specs/2026-08-04-profile-account-split-design.md)."""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="me@example.com", password="x", display_name="Me")


@pytest.fixture
def other() -> User:
    return User.objects.create_user(email="you@example.com", password="x", display_name="You")


def test_owner_sees_the_edit_and_preview_links(client: Client, user: User) -> None:
    client.force_login(user)
    body = client.get(user.get_absolute_url()).content
    assert b"Edit my profile" in body
    assert b"View as member" in body


def test_preview_hides_every_owner_control(client: Client, user: User) -> None:
    client.force_login(user)
    body = client.get(user.get_absolute_url() + "?preview=member").content
    assert b"Edit my profile" not in body
    assert b"View as member" not in body
    assert b"Back to my profile" in body

    # The nav (present on every authenticated page) always carries "Add your
    # credit", so the owner-control check must scope to <main> to still prove
    # anything about the profile page itself.
    main = body.decode()
    main = main[main.index("<main") : main.index("</main>")]
    assert "Add your credit" not in main


def test_preview_hides_credit_edit_and_delete_links(client: Client, user: User) -> None:
    """A regression reverting the credit-row guards to `user == profile_user`
    (still true in preview) would leak Edit/Delete links to the owner's own
    preview of the member view."""
    game = Game.objects.create(title="Celeste", source=Game.Source.MANUAL)
    contribution = Contribution.objects.create(
        user=user,
        game=game,
        discipline=Discipline.objects.get(name="Design"),
        job_title="Level Designer",
        start_date=date(2018, 1, 1),
    )
    client.force_login(user)

    body = client.get(user.get_absolute_url() + "?preview=member").content.decode()

    assert reverse("contributions:edit", kwargs={"pk": contribution.pk}) not in body
    assert reverse("contributions:delete", kwargs={"pk": contribution.pk}) not in body


def test_preview_renders_contact_inert(client: Client, user: User) -> None:
    """The label is shown so the owner knows members can reach them, but it is
    not a link: contacting yourself is refused by the relay, a dead end."""
    client.force_login(user)
    body = client.get(user.get_absolute_url() + "?preview=member").content.decode()
    assert "Message" in body
    assert reverse("contact:contact", kwargs={"slug": user.slug}) not in body


def test_preview_hides_contact_when_not_contactable(client: Client, user: User) -> None:
    user.contactable = False  # ty: ignore[invalid-assignment]
    user.save(update_fields=["contactable"])
    client.force_login(user)
    body = client.get(user.get_absolute_url() + "?preview=member").content
    assert b"Message" not in body


def test_preview_param_is_inert_for_a_visitor(client: Client, user: User, other: User) -> None:
    """A third party already sees the member view — the param must not give them
    a different page, and must not strip their real Message button."""
    client.force_login(other)
    body = client.get(user.get_absolute_url() + "?preview=member").content.decode()
    assert "Back to my profile" not in body
    assert reverse("contact:contact", kwargs={"slug": user.slug}) in body


def test_preview_param_is_inert_for_an_anonymous_visitor(client: Client, user: User) -> None:
    """Pins the `is_visitor` half of the flag too: a flag computed as `not is_self`
    instead of `is_authenticated and not is_self` would leak the member-only Report
    affordance here, and every other test in this file would stay green.

    The Message button is deliberately NOT pinned as absent any more — since spec
    2026-08-24 §2 it renders for anonymous visitors as well, and its own matrix
    lives in `test_message_button.py`."""
    response = client.get(user.get_absolute_url() + "?preview=member")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Back to my profile" not in body
    assert reverse("contact:report") not in body

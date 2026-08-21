"""The share row — the nudge that starts the share loop. Owner-only; a private
profile gets the invitation to go public instead (spec §3)."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db


def _main(body: str) -> str:
    return body[body.index("<main") : body.index("</main>")]


def test_owner_sees_copy_link_networks_and_preview(client: Client) -> None:
    user = User.objects.create_user(email="o@example.com", password="x", display_name="Owner")
    client.force_login(user)
    main = _main(client.get(reverse("accounts:profile", args=[user.slug])).content.decode())
    assert "Share your profile" in main and "Copy link" in main
    assert "linkedin.com/sharing/share-offsite/?url=http%3A%2F%2Ftestserver%2Fu%2F" in main
    assert "bsky.app/intent/compose?text=" in main
    assert "twitter.com/intent/tweet?" in main
    assert reverse("cards:profile", args=[user.slug]) in main


def test_visitors_never_see_the_row(client: Client) -> None:
    owner = User.objects.create_user(email="o@example.com", password="x", display_name="Owner")
    other = User.objects.create_user(email="v@example.com", password="x", display_name="V")
    client.force_login(other)
    assert "Share your profile" not in _main(
        client.get(reverse("accounts:profile", args=[owner.slug])).content.decode()
    )
    client.logout()
    assert "Share your profile" not in _main(
        client.get(reverse("accounts:profile", args=[owner.slug])).content.decode()
    )


def test_private_owner_is_invited_to_go_public(client: Client) -> None:
    user = User.objects.create_user(
        email="p@example.com", password="x", display_name="P", profile_public=False
    )
    client.force_login(user)
    main = _main(client.get(reverse("accounts:profile", args=[user.slug])).content.decode())
    assert "make it public to share it" in main
    assert "Copy link" not in main

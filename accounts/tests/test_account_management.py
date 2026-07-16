"""Account deletion + JSON export — GDPR, non-negotiable test zone #3.

Model-level cascade/anonymization is covered in test_deletion.py; here we
test the user-facing views (confirmation, avatar-file deletion, JSON export).
"""

from datetime import date
from io import BytesIO

import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from PIL import Image

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="me@example.com", password="x", display_name="Me")


def _png() -> SimpleUploadedFile:
    buffer = BytesIO()
    Image.new("RGB", (1, 1)).save(buffer, "PNG")
    return SimpleUploadedFile("avatar.png", buffer.getvalue(), content_type="image/png")


# --- Export -----------------------------------------------------------------


def test_export_requires_login(client: Client) -> None:
    assert client.get(reverse("accounts:export_data")).status_code == 302


def test_export_returns_json_attachment_with_identity_and_credits(
    client: Client, user: User
) -> None:
    game = Game.objects.create(title="Some Game", source=Game.Source.MANUAL)
    Contribution.objects.create(
        user=user,
        game=game,
        discipline=Discipline.objects.get(name="Programming"),
        job_title="Gameplay Dev",
        start_date=date(2021, 3, 1),
    )
    user.github_login = "torvalds"  # ty: ignore[invalid-assignment]
    user.save(update_fields=["github_login"])
    client.force_login(user)

    response = client.get(reverse("accounts:export_data"))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert "attachment" in response["Content-Disposition"]
    data = response.json()
    assert data["identity"]["email"] == "me@example.com"
    assert data["identity"]["github_login"] == "torvalds"
    assert data["contributions"][0]["job_title"] == "Gameplay Dev"
    assert data["contributions"][0]["game"] == "Some Game"


def test_export_includes_country(client: Client) -> None:
    user = User.objects.create_user(
        email="me@example.com", password="x", display_name="Me", country="SE"
    )
    client.force_login(user)
    data = client.get(reverse("accounts:export_data")).json()
    assert data["identity"]["country"] == "SE"


# --- Deletion ---------------------------------------------------------------


def test_delete_requires_login(client: Client) -> None:
    assert client.get(reverse("accounts:account_delete")).status_code == 302


def test_delete_page_shows_confirmation(client: Client, user: User) -> None:
    client.force_login(user)
    response = client.get(reverse("accounts:account_delete"))
    assert response.status_code == 200


def test_delete_removes_account_and_cascades_contributions(client: Client, user: User) -> None:
    game = Game.objects.create(title="Some Game", source=Game.Source.MANUAL)
    Contribution.objects.create(
        user=user,
        game=game,
        discipline=Discipline.objects.get(name="Programming"),
        job_title="Dev",
        start_date=date(2020, 1, 1),
    )
    client.force_login(user)

    response = client.post(reverse("accounts:account_delete"))

    assert response.status_code == 302
    assert not User.objects.filter(pk=user.pk).exists()
    assert Contribution.objects.count() == 0  # cascaded
    assert not response.wsgi_request.user.is_authenticated  # logged out


def test_delete_removes_the_avatar_file(client: Client, user: User) -> None:
    # avatar is a FieldFile at runtime; the type checker sees the ImageField.
    user.avatar.save("avatars/me.png", _png(), save=True)  # ty: ignore[unresolved-attribute]
    stored_name = user.avatar.name
    assert default_storage.exists(stored_name)
    client.force_login(user)

    client.post(reverse("accounts:account_delete"))

    assert not default_storage.exists(stored_name)  # GDPR: avatar object deleted

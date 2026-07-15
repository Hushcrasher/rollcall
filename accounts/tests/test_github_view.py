"""github_activity fragment view — never breaks the profile page."""

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts import github as gh
from accounts.models import GitHubSnapshot, User

pytestmark = pytest.mark.django_db


def _user(**kw: Any) -> User:
    defaults = dict(email="v@example.com", password="x", display_name="V", github_login="torvalds")
    defaults.update(kw)
    return User.objects.create_user(**defaults)


def _url(user: User) -> str:
    return reverse("accounts:github_activity", kwargs={"slug": user.slug})


def test_renders_ok_block_from_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    GitHubSnapshot.objects.create(
        user=user,
        login="torvalds",
        public_repos=7,
        status=GitHubSnapshot.Status.OK,
        profile_fetched_at=timezone.now(),
    )
    # Freshness: no network. Force the service to serve from DB.
    monkeypatch.setattr(gh, "_needs_refresh", lambda *a, **k: False)

    response = Client().get(_url(user))
    assert response.status_code == 200
    assert b"Public side projects" in response.content
    assert b"7" in response.content


def test_hidden_when_no_login() -> None:
    user = _user(github_login="")
    response = Client().get(_url(user))
    assert response.status_code == 200
    assert b"Public side projects" not in response.content


def test_never_500s_when_service_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    monkeypatch.setattr(gh, "get_github_activity", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    response = Client().get(_url(user))
    assert response.status_code == 200  # degraded, not crashed


def test_private_profile_is_404_to_others() -> None:
    user = _user(profile_public=False)
    response = Client().get(_url(user))
    assert response.status_code == 404


def test_never_leaks_email(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    GitHubSnapshot.objects.create(
        user=user, login="torvalds", public_repos=1,
        status=GitHubSnapshot.Status.OK, profile_fetched_at=timezone.now(),
    )
    monkeypatch.setattr(gh, "_needs_refresh", lambda *a, **k: False)
    response = Client().get(_url(user))
    assert b"v@example.com" not in response.content

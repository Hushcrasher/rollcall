"""github_activity fragment view — never breaks the profile page."""

from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import GitHubSnapshot, User

pytestmark = pytest.mark.django_db


def _user(**kw: Any) -> User:
    defaults = dict(email="v@example.com", password="x", display_name="V", github_login="torvalds")
    defaults.update(kw)
    return User.objects.create_user(**defaults)


def _url(user: User) -> str:
    return reverse("accounts:github_activity", kwargs={"slug": user.slug})


def test_renders_ok_block_from_cache() -> None:
    user = _user()
    GitHubSnapshot.objects.create(
        user=user,
        login="torvalds",
        public_repos=7,
        status=GitHubSnapshot.Status.OK,
        profile_fetched_at=timezone.now(),
    )
    # With GITHUB_TOKEN="" the client is unconfigured: no network, cached data served.
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
    from accounts import views

    user = _user()

    def _boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("x")

    monkeypatch.setattr(views, "get_github_activity", _boom)
    response = Client().get(_url(user))
    assert response.status_code == 200  # degraded, not crashed


def test_private_profile_is_404_to_others() -> None:
    user = _user(profile_public=False)
    response = Client().get(_url(user))
    assert response.status_code == 404


def test_never_leaks_email() -> None:
    user = _user()
    GitHubSnapshot.objects.create(
        user=user, login="torvalds", public_repos=1,
        status=GitHubSnapshot.Status.OK, profile_fetched_at=timezone.now(),
    )
    # With GITHUB_TOKEN="" the client is unconfigured: no network, cached data served.
    response = Client().get(_url(user))
    assert b"v@example.com" not in response.content


def test_is_rate_limited(client: Client, settings: Any) -> None:
    settings.RATELIMIT_ENABLE = True
    settings.PROFILE_RATELIMIT = "1/m"
    cache.clear()  # rate counters live in the cache

    user = _user()
    url = _url(user)
    first = client.get(url)
    second = client.get(url)

    assert first.status_code == 200
    assert second.status_code == 403  # rate limited

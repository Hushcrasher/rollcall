"""SettingsForm.github_url — parse to a login and manage the cache."""

import pytest
from django.utils import timezone

from accounts.forms import SettingsForm
from accounts.models import GitHubSnapshot, GitHubYearlyContribution, User

pytestmark = pytest.mark.django_db


def _user(**kw: str) -> User:
    return User.objects.create_user(email="f@example.com", password="x", display_name="F", **kw)


def _data(**overrides: str) -> dict[str, str]:
    data = {
        "display_name": "F",
        "bio": "",
        "location": "",
        "profile_public": "on",
        "contactable": "on",
        "open_to_work": "",
        "github_url": "",
    }
    data.update(overrides)
    return data


def test_valid_url_is_stored_as_login() -> None:
    user = _user()
    form = SettingsForm(_data(github_url="https://github.com/torvalds"), instance=user)
    assert form.is_valid(), form.errors
    form.save()
    user.refresh_from_db()
    assert user.github_login == "torvalds"


def test_repo_url_keeps_first_segment() -> None:
    user = _user()
    form = SettingsForm(_data(github_url="github.com/torvalds/linux"), instance=user)
    assert form.is_valid(), form.errors
    form.save()
    user.refresh_from_db()
    assert user.github_login == "torvalds"


def test_invalid_url_is_a_validation_error() -> None:
    form = SettingsForm(_data(github_url="not a url !!"), instance=_user())
    assert not form.is_valid()
    assert "github_url" in form.errors


def test_initial_prefills_from_existing_login() -> None:
    user = _user(github_login="torvalds")
    form = SettingsForm(instance=user)
    assert form.fields["github_url"].initial == "torvalds"


def test_changing_the_handle_wipes_the_cache() -> None:
    user = _user(github_login="torvalds")
    GitHubSnapshot.objects.create(user=user, login="torvalds")
    GitHubYearlyContribution.objects.create(user=user, year=2024, fetched_at=timezone.now())

    form = SettingsForm(_data(github_url="github.com/gvanrossum"), instance=user)
    assert form.is_valid(), form.errors
    form.save()

    assert not GitHubSnapshot.objects.filter(user=user).exists()
    assert not GitHubYearlyContribution.objects.filter(user=user).exists()
    user.refresh_from_db()
    assert user.github_login == "gvanrossum"


def test_unchanged_handle_keeps_the_cache() -> None:
    user = _user(github_login="torvalds")
    GitHubSnapshot.objects.create(user=user, login="torvalds")
    form = SettingsForm(_data(github_url="https://github.com/torvalds"), instance=user)
    assert form.is_valid(), form.errors
    form.save()
    assert GitHubSnapshot.objects.filter(user=user).exists()

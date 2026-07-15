"""get_github_activity — cache-aside with a DB-backed TTL."""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from accounts.github import GitHubClient, GitHubError, GitHubNotFound, get_github_activity
from accounts.models import GitHubSnapshot, GitHubYearlyContribution, User

pytestmark = pytest.mark.django_db


class FakeClient:
    """Configured stub that counts calls; no network."""

    def __init__(self, years: list[int] | None = None, raise_on: str | None = None) -> None:
        self.years = years if years is not None else [timezone.now().year, timezone.now().year - 1]
        self.raise_on = raise_on
        self.calls: list[str] = []

    configured = True

    def get_profile(self, login: str) -> dict[str, Any]:
        self.calls.append("profile")
        if self.raise_on == "profile":
            raise GitHubError("boom")
        if self.raise_on == "not_found":
            raise GitHubNotFound("ghost")
        return {
            "public_repos": 7,
            "followers": 2,
            "avatar_url": "a",
            "created_at": "2013-05-01T00:00:00Z",
        }

    def get_contribution_years(self, login: str) -> list[int]:
        self.calls.append("years")
        return self.years

    def get_year_contributions(self, login: str, year: int) -> dict[str, int]:
        self.calls.append(f"year:{year}")
        return {
            "total_commits": 10 + year % 5,
            "private_count": year % 3,
            "total_contributions": 20,
        }


def _user(login: str = "torvalds") -> User:
    return User.objects.create_user(
        email="s@example.com", password="x", display_name="S", github_login=login
    )


def test_no_login_returns_none() -> None:
    assert get_github_activity(_user(login=""), FakeClient()) is None


def test_unconfigured_client_returns_none() -> None:
    assert get_github_activity(_user(), GitHubClient(token="")) is None


def test_cold_fetch_fetches_profile_years_and_each_year() -> None:
    user = _user()
    client = FakeClient(years=[2026, 2025, 2024])
    activity = get_github_activity(user, client)

    assert activity is not None
    assert activity.status == "ok"
    assert activity.public_repos == 7
    assert client.calls == ["profile", "years", "year:2026", "year:2025", "year:2024"]
    assert GitHubYearlyContribution.objects.get(user=user, year=2024).is_final is True
    assert GitHubYearlyContribution.objects.get(user=user, year=2026).is_final is False


def test_history_is_capped_at_five_years() -> None:
    user = _user()
    client = FakeClient(years=[2026, 2025, 2024, 2023, 2022, 2021, 2020])
    get_github_activity(user, client)
    assert GitHubYearlyContribution.objects.filter(user=user).count() == 5
    assert not GitHubYearlyContribution.objects.filter(user=user, year=2021).exists()


def test_warm_and_fresh_makes_no_calls() -> None:
    user = _user()
    get_github_activity(user, FakeClient())  # cold
    client = FakeClient()
    get_github_activity(user, client)  # warm
    assert client.calls == []


def test_stale_current_year_does_one_partial_fetch() -> None:
    user = _user()
    get_github_activity(user, FakeClient())  # cold
    current_year = timezone.now().year
    row = GitHubYearlyContribution.objects.get(user=user, year=current_year)
    row.fetched_at = timezone.now() - timedelta(hours=25)
    row.save(update_fields=["fetched_at"])

    client = FakeClient()
    get_github_activity(user, client)
    assert client.calls == ["profile", f"year:{current_year}"]  # NOT the whole history


def test_not_found_is_recorded_and_not_retried_for_7_days() -> None:
    user = _user()
    client = FakeClient(raise_on="not_found")
    activity = get_github_activity(user, client)
    assert activity is not None
    assert activity.status == "not_found"

    client2 = FakeClient(raise_on="not_found")
    get_github_activity(user, client2)
    assert client2.calls == []  # no retry within 7 days


def test_error_serves_stale_data() -> None:
    user = _user()
    get_github_activity(user, FakeClient())  # good cold fetch
    current_year = timezone.now().year
    row = GitHubYearlyContribution.objects.get(user=user, year=current_year)
    row.fetched_at = timezone.now() - timedelta(hours=25)
    row.save(update_fields=["fetched_at"])

    activity = get_github_activity(user, FakeClient(raise_on="profile"))
    assert activity is not None
    assert activity.public_repos == 7  # stale-but-present data still served
    snap = GitHubSnapshot.objects.get(user=user)
    assert snap.status == GitHubSnapshot.Status.ERROR
    assert snap.last_error


def test_error_on_cold_fetch_then_recovery_does_a_full_backfill() -> None:
    user = _user()
    # First-ever fetch errors before any yearly rows are persisted.
    get_github_activity(user, FakeClient(raise_on="profile"))
    assert not GitHubYearlyContribution.objects.filter(user=user).exists()
    snap = GitHubSnapshot.objects.get(user=user)
    assert snap.status == GitHubSnapshot.Status.ERROR
    # Age past the 24h error back-off.
    snap.profile_fetched_at = timezone.now() - timedelta(hours=25)
    snap.save(update_fields=["profile_fetched_at"])
    # Recovery must FULL-fetch (backfill history), not partial.
    client = FakeClient(years=[2026, 2025, 2024])
    activity = get_github_activity(user, client)
    assert activity is not None and activity.status == "ok"
    assert client.calls == ["profile", "years", "year:2026", "year:2025", "year:2024"]
    assert GitHubYearlyContribution.objects.filter(user=user).count() == 3

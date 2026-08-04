"""GitHub cache models — snapshot + per-year contributions."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from accounts.models import GitHubSnapshot, GitHubYearlyContribution, User

pytestmark = pytest.mark.django_db


def _user() -> User:
    return User.objects.create_user(email="g@example.com", password="x", display_name="G")


def test_snapshot_is_one_per_user() -> None:
    user = _user()
    GitHubSnapshot.objects.create(user=user, login="torvalds")
    with pytest.raises(IntegrityError):
        GitHubSnapshot.objects.create(user=user, login="torvalds2")


def test_snapshot_defaults_to_never_fetched() -> None:
    snap = GitHubSnapshot.objects.create(user=_user(), login="torvalds")
    assert snap.status == GitHubSnapshot.Status.NEVER_FETCHED
    assert snap.public_repos is None


def test_yearly_rows_are_unique_per_user_year() -> None:
    user = _user()
    now = timezone.now()
    GitHubYearlyContribution.objects.create(user=user, year=2024, fetched_at=now, is_final=True)
    with pytest.raises(IntegrityError):
        GitHubYearlyContribution.objects.create(user=user, year=2024, fetched_at=now)


def test_user_github_login_defaults_blank() -> None:
    assert _user().github_login == ""


def test_github_login_rejects_invalid_handle_at_model_level() -> None:
    """Writes that bypass ProfileForm (admin, shell) must still be caught —
    the login regex is enforced as a model validator, not just in the form."""
    user = _user()
    user.github_login = "-badstart"  # ty: ignore[invalid-assignment]  # cannot start with a hyphen

    with pytest.raises(ValidationError):
        user.full_clean()

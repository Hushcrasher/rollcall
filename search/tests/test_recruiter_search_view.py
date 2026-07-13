"""Recruiter search view — gated to recruiter accounts."""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def recruiter() -> User:
    return User.objects.create_user(
        email="rec@example.com", password="x", display_name="Rec", role=User.Role.RECRUITER
    )


def test_search_requires_login(client: Client) -> None:
    assert client.get(reverse("search:recruiter_search")).status_code == 302


def test_non_recruiter_is_redirected_to_apply(client: Client) -> None:
    member = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(member)
    response = client.get(reverse("search:recruiter_search"))
    assert response.status_code == 302
    assert reverse("accounts:recruiter_apply") in response.url


def test_recruiter_sees_the_form(client: Client, recruiter: User) -> None:
    client.force_login(recruiter)
    response = client.get(reverse("search:recruiter_search"))
    assert response.status_code == 200
    assert b"discipline" in response.content.lower()


def test_recruiter_search_returns_matches_without_leaking_email(
    client: Client, recruiter: User
) -> None:
    design = Discipline.objects.get(name="Design")
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    candidate = User.objects.create_user(
        email="candidate@example.com", password="x", display_name="Great Candidate"
    )
    Contribution.objects.create(
        user=candidate,
        game=game,
        discipline=design,
        job_title="Designer",
        start_date=date(2020, 1, 1),
    )
    client.force_login(recruiter)

    response = client.get(reverse("search:recruiter_search"), {"discipline": design.pk})

    assert b"Great Candidate" in response.content
    assert b"candidate@example.com" not in response.content

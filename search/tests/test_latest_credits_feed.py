"""The home feed — social proof on the bare front door. The guards ARE the
feature: only active credits of public profiles, nothing else about the user
(spec 2026-08-20-mobile-first-surface §3)."""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


def _credit(
    email: str,
    name: str,
    *,
    status: str = Contribution.Status.ACTIVE,
    profile_public: bool = True,
    title: str = "Card Game",
) -> Contribution:
    game, _ = Game.objects.get_or_create(title=title, defaults={"source": Game.Source.MANUAL})
    user = User.objects.create_user(
        email=email, password="x", display_name=name, profile_public=profile_public
    )
    return Contribution.objects.create(
        user=user,
        game=game,
        discipline=Discipline.objects.get(name="Design"),
        job_title="Level Designer",
        start_date=date(2024, 8, 1),
        end_date=date(2025, 3, 1),
        status=status,
    )


def test_feed_shows_active_public_credits_with_mm_yyyy_dates(client: Client) -> None:
    _credit("a@example.com", "Ada Artist")
    body = client.get(reverse("home")).content.decode()
    assert "Latest credits" in body
    assert "Ada Artist" in body
    assert "added a credit on" in body
    assert "Card Game" in body
    assert "Level Designer" in body
    assert "08/2024" in body and "03/2025" in body


def test_feed_never_shows_pending_credits(client: Client) -> None:
    _credit("p@example.com", "Pending Person", status=Contribution.Status.PENDING)
    body = client.get(reverse("home")).content.decode()
    assert "Pending Person" not in body


def test_feed_never_shows_private_profiles(client: Client) -> None:
    _credit("h@example.com", "Hidden Person", profile_public=False)
    body = client.get(reverse("home")).content.decode()
    assert "Hidden Person" not in body


def test_feed_is_absent_once_a_search_ran(client: Client) -> None:
    _credit("a@example.com", "Ada Artist")
    design = Discipline.objects.get(name="Design")
    body = client.get(reverse("home"), {"discipline": str(design.pk)}).content.decode()
    assert "Latest credits" not in body


def test_feed_is_newest_first_and_capped_at_ten(client: Client) -> None:
    for i in range(11):
        _credit(f"u{i}@example.com", f"Person {i:02d}", title=f"Game {i:02d}")
    body = client.get(reverse("home")).content.decode()
    assert "Person 10" in body  # newest
    assert "Person 00" not in body  # 11th-newest fell off
    assert body.index("Person 10") < body.index("Person 01")


def test_result_card_credit_dates_render_mm_yyyy(client: Client) -> None:
    _credit("a@example.com", "Ada Artist")
    design = Discipline.objects.get(name="Design")
    body = client.get(reverse("home"), {"discipline": str(design.pk)}).content.decode()
    assert "08/2024" in body and "03/2025" in body

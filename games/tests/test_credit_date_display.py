"""Game-page team list — same m/Y display rule as profiles (spec 2026-08-20 §4)."""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


def test_game_page_credit_dates_render_mm_yyyy(client: Client) -> None:
    game = Game.objects.create(title="Date Game", source=Game.Source.MANUAL)
    user = User.objects.create_user(
        email="dates@example.com", password="x", display_name="Date Person"
    )
    Contribution.objects.create(
        user=user,
        game=game,
        discipline=Discipline.objects.get(name="Design"),
        job_title="Animator",
        start_date=date(2024, 8, 1),
        end_date=date(2025, 3, 1),
    )
    body = client.get(reverse("games:game", args=[game.slug])).content.decode()
    assert "08/2024" in body and "03/2025" in body
    assert "Aug 2024" not in body

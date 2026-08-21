"""The home feed — social proof on the bare front door. The guards ARE the
feature: only active credits of public profiles, nothing else about the user
(spec 2026-08-20-mobile-first-surface §3)."""

from datetime import date
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Company, Game

pytestmark = pytest.mark.django_db

_TEMPLATE = Path(settings.BASE_DIR) / "templates" / "search" / "people_search.html"


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


def test_feed_skips_credits_without_a_game(client: Client) -> None:
    """`Contribution.game` is nullable — the check constraint takes a company
    instead. The feed line links the game, so a null one renders a link to
    nowhere on the home page of a public site."""
    credit = _credit("g@example.com", "Gameless Person")
    studio = Company.objects.create(name="Studio", source=Company.Source.MANUAL)
    Contribution.objects.filter(pk=credit.pk).update(game=None, company=studio)
    response = client.get(reverse("home"))
    assert response.status_code == 200
    assert "Gameless Person" not in response.content.decode()


def test_feed_is_absent_once_a_search_ran(client: Client) -> None:
    _credit("a@example.com", "Ada Artist")
    design = Discipline.objects.get(name="Design")
    body = client.get(reverse("home"), {"discipline": str(design.pk)}).content.decode()
    assert "Latest credits" not in body


def test_feed_survives_an_unrelated_tracking_param(client: Client) -> None:
    # `?utm_source=...`/`?fbclid=...` on a tagged inbound link are not a
    # search — the feed is keyed on RecruiterSearchForm's own filter fields,
    # not on bare `bool(request.GET)`, so an unknown param must not swap the
    # feed out for an empty results block, and must not bind the form either
    # (a bound-but-empty form's clean() error would render alongside it).
    _credit("a@example.com", "Ada Artist")
    body = client.get(reverse("home"), {"utm_source": "newsletter"}).content.decode()
    assert "Latest credits" in body
    assert "Ada Artist" in body
    assert "Pick at least one filter." not in body


def test_feed_survives_a_bare_page_param(client: Client) -> None:
    # `?page=2` alone (no real filter) is not a search either — same
    # reasoning as the tracking-param case above, for the one other
    # non-form key the view reads directly off request.GET.
    _credit("a@example.com", "Ada Artist")
    body = client.get(reverse("home"), {"page": "2"}).content.decode()
    assert "Latest credits" in body
    assert "Ada Artist" in body
    assert "Pick at least one filter." not in body


def test_the_feed_sentence_is_one_translation_unit_not_split_around_a_link() -> None:
    """`{% translate "added a credit on" %}` sandwiched between the two links
    fixes English word order in place. One {% blocktranslate %} keeps the
    sentence whole, with only the two links' URLs as placeholders."""
    source = _TEMPLATE.read_text()
    assert '{% translate "added a credit on" %}' not in source
    assert "{% blocktranslate" in source
    assert "added a credit on" in source


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
    # The defect this fixed was `date:"M Y"`, which renders both forms' digits
    # differently — without this the card could show BOTH and still pass.
    assert "Aug 2024" not in body

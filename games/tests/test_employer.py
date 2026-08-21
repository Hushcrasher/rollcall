"""Employer field helpers — the game's studios as a preselected <select> +
create-company (spec 2026-08-21-credit-form-v2 §1)."""

import re

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from games.models import Company, Game, GameCompany

pytestmark = pytest.mark.django_db


def test_game_employers_lists_the_games_companies(client: Client) -> None:
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    dev = Company.objects.create(name="Supergiant Games", source=Company.Source.MANUAL)
    pub = Company.objects.create(name="Private Division", source=Company.Source.MANUAL)
    GameCompany.objects.create(game=game, company=dev, role=GameCompany.Role.DEVELOPER)
    GameCompany.objects.create(game=game, company=pub, role=GameCompany.Role.PUBLISHER)

    response = client.get(reverse("games:game_employers", kwargs={"pk": game.pk}))
    body = response.content.decode()

    assert response.status_code == 200
    assert "<select" in body
    assert f'<option value="{dev.pk}"' in body
    assert "Supergiant Games" in body
    assert "Private Division" in body
    assert "another company" in body.lower()  # the "other" fallback


def test_game_employers_dedupes_a_company_with_multiple_roles(client: Client) -> None:
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    studio = Company.objects.create(name="Supergiant Games", source=Company.Source.MANUAL)
    GameCompany.objects.create(game=game, company=studio, role=GameCompany.Role.DEVELOPER)
    GameCompany.objects.create(game=game, company=studio, role=GameCompany.Role.PUBLISHER)

    body = client.get(reverse("games:game_employers", kwargs={"pk": game.pk})).content.decode()

    assert body.count(f'<option value="{studio.pk}"') == 1


def test_game_employers_orders_developer_publisher_porting_supporting(client: Client) -> None:
    """The select's option order is by role relevance, not by the enum strings'
    alphabetical order (which would put porting before publisher)."""
    game = Game.objects.create(title="Dark Souls", source=Game.Source.MANUAL)
    porting = Company.objects.create(name="QLOC", source=Company.Source.MANUAL)
    pub = Company.objects.create(name="Bandai Namco", source=Company.Source.MANUAL)
    dev = Company.objects.create(name="FromSoftware", source=Company.Source.MANUAL)
    GameCompany.objects.create(game=game, company=porting, role=GameCompany.Role.PORTING)
    GameCompany.objects.create(game=game, company=pub, role=GameCompany.Role.PUBLISHER)
    GameCompany.objects.create(game=game, company=dev, role=GameCompany.Role.DEVELOPER)

    body = client.get(reverse("games:game_employers", kwargs={"pk": game.pk})).content.decode()

    assert body.index("FromSoftware") < body.index("Bandai Namco") < body.index("QLOC")


def test_employer_select_preselects_the_developer_and_offers_the_two_escapes(
    client: Client,
) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    dev = Company.objects.create(name="Dev Studio", source=Company.Source.MANUAL)
    pub = Company.objects.create(name="Pub Corp", source=Company.Source.MANUAL)
    GameCompany.objects.create(game=game, company=pub, role=GameCompany.Role.PUBLISHER)
    GameCompany.objects.create(game=game, company=dev, role=GameCompany.Role.DEVELOPER)
    body = client.get(reverse("games:game_employers", args=[game.pk])).content.decode()
    assert "<select" in body
    assert re.search(rf'<option value="{dev.pk}" selected>Dev Studio \(', body)
    assert body.index("Dev Studio") < body.index("Pub Corp")
    assert '<option value="">No employer / freelance</option>' in body
    assert '<option value="__other">Another company…</option>' in body


def test_employer_select_without_companies_defaults_to_no_employer(client: Client) -> None:
    game = Game.objects.create(title="Solo", source=Game.Source.MANUAL)
    body = client.get(reverse("games:game_employers", args=[game.pk])).content.decode()
    assert '<option value="" selected>No employer / freelance</option>' in body


def test_employer_select_has_no_leaked_template_comment(client: Client) -> None:
    """`{# ... #}` can't span lines in Django — a multi-line one is rendered
    literally instead of stripped, which would corrupt the fragment swapped
    into the page. `templates/games/_employer_options.html`'s own
    `{% comment %}` block explains why it is written the way it is."""
    game = Game.objects.create(title="Solo", source=Game.Source.MANUAL)
    body = client.get(reverse("games:game_employers", args=[game.pk])).content.decode()
    assert "{#" not in body


def test_employer_select_keeps_a_saved_company_that_is_not_linked_to_the_game(
    client: Client,
) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    other = Company.objects.create(name="Outsourcing Ltd", source=Company.Source.MANUAL)
    body = client.get(
        reverse("games:game_employers", args=[game.pk]), {"selected": other.pk}
    ).content.decode()
    assert re.search(rf'<option value="{other.pk}" selected>Outsourcing Ltd', body)


def test_employer_select_ignores_a_selected_that_is_not_an_integer(client: Client) -> None:
    """`?selected=²` must answer the default selection, not 500: `"²".isdigit()`
    is True while `int("²")` raises (the same trap `DeclareGameView._picked_game`
    already guards against with `isdecimal()`)."""
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    dev = Company.objects.create(name="Dev Studio", source=Company.Source.MANUAL)
    GameCompany.objects.create(game=game, company=dev, role=GameCompany.Role.DEVELOPER)

    response = client.get(reverse("games:game_employers", args=[game.pk]), {"selected": "²"})

    assert response.status_code == 200
    assert re.search(rf'<option value="{dev.pk}" selected>Dev Studio \(', response.content.decode())


def test_selected_none_keeps_the_credit_employer_less(client: Client) -> None:
    """`?selected=none` is "the form knows there is no employer" (a freelance
    credit being edited, or a member who picked `No employer / freelance`) —
    as opposed to an absent `selected`, which means "unknown" and takes the
    developer-first default. Preselecting the developer here would let a typo
    fix on a freelance credit silently stamp the studio as employer."""
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    dev = Company.objects.create(name="Dev Studio", source=Company.Source.MANUAL)
    GameCompany.objects.create(game=game, company=dev, role=GameCompany.Role.DEVELOPER)

    body = client.get(
        reverse("games:game_employers", args=[game.pk]), {"selected": "none"}
    ).content.decode()

    assert '<option value="" selected>No employer / freelance</option>' in body
    assert f'<option value="{dev.pk}" selected' not in body


def test_company_create_requires_login(client: Client) -> None:
    response = client.post(reverse("games:company_create"), {"name": "Virtuos"})
    assert response.status_code == 302
    assert not Company.objects.filter(name="Virtuos").exists()  # nothing was written


def test_company_create_rejects_an_overlong_name(client: Client) -> None:
    # Company.name is varchar(300); an unchecked longer value would be a raw
    # DataError 500. The endpoint must answer 400 like its "name required" case.
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)

    response = client.post(reverse("games:company_create"), {"name": "V" * 301})

    assert response.status_code == 400
    assert Company.objects.count() == 0


def test_company_create_makes_a_manual_company_and_returns_json(client: Client) -> None:
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)

    response = client.post(reverse("games:company_create"), {"name": "Virtuos"})

    assert response.status_code == 200
    company = Company.objects.get(name="Virtuos")
    assert company.source == Company.Source.MANUAL
    assert response.json() == {"id": company.pk, "label": "Virtuos"}


def test_company_create_is_idempotent(client: Client) -> None:
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)
    client.post(reverse("games:company_create"), {"name": "Virtuos"})
    client.post(reverse("games:company_create"), {"name": "Virtuos"})
    assert Company.objects.filter(name="Virtuos").count() == 1

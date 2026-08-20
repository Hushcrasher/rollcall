"""base.html wiring — the style layer is two stylesheets, Pico (vendored) and
the functional-only app.css (spec 2026-08-20-mobile-first-surface §1)."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_every_page_links_pico_then_app_css(client: Client) -> None:
    body = client.get(reverse("home")).content.decode()
    pico = body.index("vendor/pico.classless.min.css")
    app = body.index("css/app.css")
    # Order matters: app.css must be able to override Pico.
    assert pico < app


def _header(body: str) -> str:
    return body[: body.index("</header>")]


def test_anonymous_nav_leads_with_the_declare_cta(client: Client) -> None:
    """The most visible nav control is the worker CTA (spec §1): role=button
    renders as Pico's one solid button on the bar. Sign up leaves the nav —
    the declare funnel IS the signup path; the login page keeps a direct link."""
    header = _header(client.get(reverse("home")).content.decode())
    assert "ROLLCALL" in header
    assert 'role="button"' in header
    assert reverse("contributions:declare") in header
    assert "Add your credit" in header
    assert "Sign up" not in header


def test_member_nav_cta_goes_to_the_credit_form(client: Client) -> None:
    user = User.objects.create_user(email="nav@example.com", password="x", display_name="N")
    client.force_login(user)
    header = _header(client.get(reverse("home")).content.decode())
    assert reverse("contributions:create") in header
    assert "Add your credit" in header

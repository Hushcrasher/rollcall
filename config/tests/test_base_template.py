"""base.html wiring — the style layer is two stylesheets, Pico (vendored) and
the functional-only app.css (spec 2026-08-20-mobile-first-surface §1)."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from conftest import header as _header

pytestmark = pytest.mark.django_db


def test_every_page_links_pico_then_app_css(client: Client) -> None:
    body = client.get(reverse("home")).content.decode()
    pico = body.index("vendor/pico.classless.min.css")
    app = body.index("css/app.css")
    # Order matters: app.css must be able to override Pico.
    assert pico < app


def test_every_page_loads_the_autocomplete_dismiss_script(client: Client) -> None:
    """Every page carries a dropdown — the nav search box — so the module that
    dismisses one is sitewide. `defer` is load-bearing: the module binds
    document-level listeners and must not run before the DOM exists. The order
    after htmx is convention, not a requirement — listening for a custom event
    needs no library loaded, and both scripts being `defer` means both run
    before any interaction anyway; the assertion keeps the two vendored-then-
    ours groups in a stable order (spec 2026-08-22-autocomplete-dismiss §1)."""
    body = client.get(reverse("home")).content.decode()
    htmx = body.index("vendor/htmx.min.js")
    module = body.index("js/autocomplete.js")
    assert htmx < module
    assert "defer" in body[module : module + 40]


def test_anonymous_nav_leads_with_the_declare_cta(client: Client) -> None:
    """The most visible nav control is the worker CTA (spec §1): role=button
    renders as Pico's one solid button on the bar. Sign up leaves the nav —
    the declare funnel IS the signup path; the login page keeps a direct link."""
    header = _header(client.get(reverse("home")).content.decode())
    # Stacked wordmark: two four-letter lines in a monospace face (spec
    # 2026-08-21-search-chrome §1) — never the one-word form.
    assert 'class="wordmark"' in header
    assert "ROLL<br>CALL" in header
    assert "ROLLCALL" not in header
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

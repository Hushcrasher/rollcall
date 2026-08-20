"""base.html wiring — the style layer is two stylesheets, Pico (vendored) and
the functional-only app.css (spec 2026-08-20-mobile-first-surface §1)."""

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_every_page_links_pico_then_app_css(client: Client) -> None:
    body = client.get(reverse("home")).content.decode()
    pico = body.index("vendor/pico.classless.min.css")
    app = body.index("css/app.css")
    # Order matters: app.css must be able to override Pico.
    assert pico < app

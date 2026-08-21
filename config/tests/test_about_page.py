"""The About page — trust surface for a site asking people to document their
careers, and the open-source invitation (spec 2026-08-20 §5)."""

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_about_renders_the_four_sections(client: Client) -> None:
    body = client.get(reverse("about")).content.decode()
    assert "What this is" in body
    assert "Where the data comes from" in body
    assert "Open source" in body
    assert "github.com/Hushcrasher/rollcall" in body
    assert "AGPL" in body


def test_footer_links_to_about(client: Client) -> None:
    body = client.get(reverse("home")).content.decode()
    footer = body[body.index("<footer") :]
    assert reverse("about") in footer


def test_about_links_the_report_form(client: Client) -> None:
    # ReportView is login-gated, but a link that bounces to login is still
    # more useful than prose telling an anonymous reader to find it
    # themselves (spec §5: "link to the report form").
    body = client.get(reverse("about")).content.decode()
    assert reverse("contact:report") in body

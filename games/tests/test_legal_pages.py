"""Legal pages — public, honest, and linked in the footer."""

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_terms_page_is_public(client: Client) -> None:
    response = client.get(reverse("terms"))
    assert response.status_code == 200
    assert b"AGPL" in response.content  # code license disclosed


def test_privacy_page_is_public(client: Client) -> None:
    response = client.get(reverse("privacy"))
    assert response.status_code == 200
    assert b"delete" in response.content.lower()  # right to erasure mentioned


def test_footer_links_to_legal_pages(client: Client) -> None:
    response = client.get(reverse("terms"))
    assert reverse("privacy").encode() in response.content
    assert reverse("terms").encode() in response.content

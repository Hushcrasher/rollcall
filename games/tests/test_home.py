"""Home page — a real landing at / (no 404 at the root)."""

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_home_is_public_and_links_to_key_pages(client: Client) -> None:
    response = client.get(reverse("home"))
    assert response.status_code == 200
    assert reverse("search:search").encode() in response.content
    assert reverse("search:recruiters_landing").encode() in response.content

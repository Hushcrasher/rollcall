"""Anti-scraping rate limiting on public pages (docs/02-ARCHITECTURE.md §5).

Rate limiting is disabled by default in the test settings; this test re-enables
it with a tiny limit to prove the guard trips.
"""

from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def target() -> User:
    return User.objects.create_user(email="p@example.com", password="x", display_name="Public")


def test_profile_blocks_excessive_requests(client: Client, target: User, settings: Any) -> None:
    settings.RATELIMIT_ENABLE = True
    settings.PROFILE_RATELIMIT = "1/m"
    cache.clear()  # rate counters live in the cache

    url = reverse("accounts:profile", kwargs={"slug": target.slug})
    first = client.get(url)
    second = client.get(url)

    assert first.status_code == 200
    assert second.status_code == 403  # rate limited


def test_search_blocks_excessive_requests(client: Client, settings: Any) -> None:
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    url = reverse("search:search")
    assert client.get(url, {"q": "x"}).status_code == 200
    assert client.get(url, {"q": "x"}).status_code == 403

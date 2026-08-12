"""Production settings — the wiring that cannot be exercised by running the app
in dev, and whose absence is invisible from the outside."""

import importlib
import sys
from collections.abc import Iterator
from types import ModuleType

import pytest
from django.core.exceptions import ImproperlyConfigured

_PROD = "config.settings.prod"


@pytest.fixture(autouse=True)
def _unimport_prod(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The tests below re-import the module to re-run its env reads, so it must
    not be left in sys.modules for the next test — or the next test file.

    SENTRY_DSN is cleared because importing prod would otherwise call
    `sentry_sdk.init()` for real, if a developer's own `.env` happens to set it
    (base.py reads that file). Tests must not depend on whose machine they run
    on — the same reasoning as config/settings/test.py's IGDB/GitHub blanking.
    """
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    sys.modules.pop(_PROD, None)
    yield
    sys.modules.pop(_PROD, None)


def _import_prod() -> ModuleType:
    return importlib.import_module(_PROD)


def test_prod_refuses_to_start_without_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """A silent fallback to LocMemCache would leave the deployment looking
    healthy while the mitigation docs/01-DESIGN.md §3.6 relies on does not hold.
    That invisibility is the whole defect this change removes, so the variable is
    required exactly like DJANGO_SECRET_KEY."""
    monkeypatch.setenv("DJANGO_SECRET_KEY", "test-only")
    monkeypatch.delenv("REDIS_URL", raising=False)

    with pytest.raises(ImproperlyConfigured):
        _import_prod()


def test_prod_wires_the_cache_to_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DJANGO_SECRET_KEY", "test-only")
    monkeypatch.setenv("REDIS_URL", "redis://redis.example:6379/0")

    caches = _import_prod().CACHES

    assert caches["default"]["BACKEND"] == "django_redis.cache.RedisCache"
    assert caches["default"]["LOCATION"] == "redis://redis.example:6379/0"
    # Without this, a connection error propagates and RATELIMIT_FAIL_OPEN never
    # runs — the outage would 500 the site instead of un-metering it.
    assert caches["default"]["OPTIONS"]["IGNORE_EXCEPTIONS"] is True

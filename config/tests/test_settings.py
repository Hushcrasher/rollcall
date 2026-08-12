"""Production settings — the wiring that cannot be exercised by running the app
in dev, and whose absence is invisible from the outside."""

import importlib
import sys
from collections.abc import Iterator
from types import ModuleType

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

_PROD = "config.settings.prod"


@pytest.fixture(autouse=True)
def _unimport_prod(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The tests below re-import the module to re-run its env reads, so it must
    not be left in sys.modules for the next test — or the next test file.

    SENTRY_DSN, S3_BUCKET_NAME and EMAIL_HOST_PASSWORD are cleared because
    importing prod would otherwise act on a developer's own `.env` (base.py
    reads that file). SENTRY_DSN would call `sentry_sdk.init()` for real.
    S3_BUCKET_NAME would flip `STORAGES["default"]` to S3 and EMAIL_HOST_PASSWORD
    would swap in the SMTP email backend — and `STORAGES` arrives via
    `from .base import *`, so that flip mutates the same dict object
    `django.conf.settings.STORAGES` already points at, leaking into every test
    that runs afterward, not just this module. Tests must not depend on whose
    machine they run on — the same reasoning as config/settings/test.py's
    IGDB/GitHub blanking.
    """
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("S3_BUCKET_NAME", raising=False)
    monkeypatch.delenv("EMAIL_HOST_PASSWORD", raising=False)
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

    with pytest.raises(ImproperlyConfigured, match="REDIS_URL"):
        _import_prod()


def test_prod_wires_the_cache_to_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DJANGO_SECRET_KEY", "test-only")
    monkeypatch.setenv("REDIS_URL", "redis://redis.example:6379/0")

    prod = _import_prod()
    caches = prod.CACHES

    assert caches["default"]["BACKEND"] == "django_redis.cache.RedisCache"
    assert caches["default"]["LOCATION"] == "redis://redis.example:6379/0"
    # Without this, a connection error propagates and RATELIMIT_FAIL_OPEN never
    # runs — the outage would 500 the site instead of un-metering it.
    assert caches["default"]["OPTIONS"]["IGNORE_EXCEPTIONS"] is True
    # Literal-string comparisons above would still pass if `django-redis` were
    # removed from pyproject.toml; this fails loudly instead of 500ing prod on
    # its first cache touch. Needs no running Redis — only the import to exist.
    assert import_string(caches["default"]["BACKEND"]) is not None
    # DJANGO_REDIS_LOGGER and the LOGGING block's `loggers` key are two
    # independently editable strings that must match for the outage to be
    # heard; nothing else pins them together.
    assert prod.DJANGO_REDIS_LOGGER in prod.LOGGING["loggers"]

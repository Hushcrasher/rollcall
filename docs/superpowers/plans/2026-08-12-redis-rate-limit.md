# Redis for the Rate Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Point the production cache at Redis so rate-limit counters are shared across gunicorn workers and stop being silently evicted, while a Redis outage leaves the site up rather than down.

**Architecture:** `base.py` keeps `LocMemCache` — dev and tests are untouched — and gains `RATELIMIT_FAIL_OPEN = True`. `prod.py` requires `REDIS_URL` (crashing at boot without it, like `DJANGO_SECRET_KEY`) and overrides `CACHES["default"]` with `django-redis` and `IGNORE_EXCEPTIONS`, plus the logging needed to keep an outage audible. No rate-limit call site, key, group or rate value changes.

**Tech Stack:** Django 6, django-ratelimit, django-redis, pytest, uv + ruff + ty.

Spec: [docs/superpowers/specs/2026-08-12-redis-rate-limit-design.md](../specs/2026-08-12-redis-rate-limit-design.md)

## Global Constraints

- Fully typed Python. Full gate before each commit: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`.
- `ty` has no Django plugin — reuse the accommodations already in the codebase (`AuthedHttpRequest`, `ClassVar` managers, `Any` bridges, `# ty: ignore[...]` with the exact rule name it prints).
- Postgres runs in Docker on port **5433** (`.env` sets `POSTGRES_PORT`). Start it with `docker compose up -d db` if a test run errors on the DB connection.
- **No test may require a running Redis.** Not in dev, not in CI.
- **No change to any rate-limit call site, key, group or rate value.** The ten `@ratelimit` / `is_ratelimited` sites in `accounts/views.py`, `search/views.py` and `contributions/views.py` are out of scope.
- **No migration.** `uv run python manage.py makemigrations --check --dry-run` must say `No changes detected`.
- Every user-facing string goes through `{% translate %}` in templates and `gettext_lazy as _` in Python. UI copy is English only. (This plan adds no user-facing copy.)
- Commit after every task. Work on a branch off `main`: `feat/redis-rate-limit`.

---

## File structure

| File | New/Modified | Responsibility |
|---|---|---|
| `config/settings/base.py` | Modify | `RATELIMIT_FAIL_OPEN`; correct two stale comments |
| `config/settings/prod.py` | Modify | required `REDIS_URL`, the django-redis cache, `DJANGO_REDIS_*`, `LOGGING` |
| `pyproject.toml` | Modify | the `django-redis` dependency; add `config` to pytest's `testpaths` |
| `search/tests/test_people_search_view.py` | Modify | the fail-open behaviour test, beside the existing rate-limit tests |
| `config/tests/__init__.py` | Create | package marker, matching `accounts/tests/`, `search/tests/` etc. |
| `config/tests/test_settings.py` | Create | the two production-settings tests |
| `DEPLOY.md` | Modify | a Redis section, the retuning warning, and the removal of the stale "before launch" bullet |
| `.env.example` | Modify | `REDIS_URL` |
| `ROADMAP.md` | Modify | close the follow-up |

---

## Task 1: Fail open, not closed

django-ratelimit's default on a cache failure is `should_limit: True` — 403 on every rate-limited view. That is the wrong trade for a mitigation the project already documents as a mitigation rather than a boundary. This task flips it and proves it, and needs no new dependency: a cache failure is simulated, so it is testable on `LocMemCache` exactly as it will behave behind Redis.

**Files:**
- Modify: `config/settings/base.py` (the `# --- Caching ---` comment block ~line 160, and the `# --- Rate limiting ---` block ~line 174)
- Modify: `search/tests/test_people_search_view.py`

**Interfaces:**
- Produces: the setting `RATELIMIT_FAIL_OPEN = True`, read by `django_ratelimit.core.get_usage`. Task 2 relies on this being in `base.py` so prod inherits it.

- [ ] **Step 1: Write the failing test**

In `search/tests/test_people_search_view.py`, add after `test_rate_limit_holds_while_other_ips_fill_the_cache`:

```python
def test_a_cache_failure_does_not_lock_everyone_out(client: Client, settings: Any) -> None:
    """django-ratelimit fails CLOSED by default: when the cache does not answer
    it returns `should_limit: True`, so a Redis outage would 403 every
    rate-limited page at once. The limit is a mitigation, not a boundary
    (docs/01-DESIGN.md §3.6) — the site staying up is worth more than a window
    of unmetered traffic.

    The failure is simulated rather than staged with a real Redis: this is
    exactly the shape django-redis's IGNORE_EXCEPTIONS produces — `add` returns
    falsy, `incr` raises — so the branch under test is the one prod will take.
    """
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    backend = caches["default"]
    url = reverse("home")
    search = {"open_to_work": "on"}

    def _dead_incr(*args: Any, **kwargs: Any) -> int:
        raise ValueError("cache unreachable")

    with (
        mock.patch.object(backend, "add", return_value=False),
        mock.patch.object(backend, "incr", side_effect=_dead_incr),
    ):
        # Well past the 1/m limit: none of these may be refused.
        for _ in range(5):
            assert client.get(url, search).status_code == 200
```

Add the imports this needs to the module's existing import block:

```python
from unittest import mock

from django.core.cache import cache, caches
```

`cache` is already imported; add `caches` beside it and `mock` at the top with the other stdlib imports. Patch `caches["default"]` — the concrete backend — and **not** the `cache` proxy: the proxy's `__setattr__` forwards to the backend while `__delattr__` does not, so patching through it restores incorrectly.

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest search/tests/test_people_search_view.py::test_a_cache_failure_does_not_lock_everyone_out -q`
Expected: FAIL — `assert 403 == 200` on the first iteration. With no `RATELIMIT_FAIL_OPEN`, `get_usage` returns `{'should_limit': True}` the moment the cache stops answering.

- [ ] **Step 3: Set the flag**

In `config/settings/base.py`, replace the rate-limiting block:

```python
# --- Rate limiting (anti-scraping on public pages) --------------------------
# Per-IP limits; tune via env. NB: counters live in CACHES["default"], which is
# per-process — add Redis in prod for limits that hold across workers.
PROFILE_RATELIMIT = env("PROFILE_RATELIMIT", default="120/m")
SEARCH_RATELIMIT = env("SEARCH_RATELIMIT", default="60/m")
```

with:

```python
# --- Rate limiting (anti-scraping on public pages) --------------------------
# Per-IP limits; tune via env. Counters live in CACHES["default"] — Redis in
# prod (config/settings/prod.py), LocMemCache in dev and tests.
PROFILE_RATELIMIT = env("PROFILE_RATELIMIT", default="120/m")
SEARCH_RATELIMIT = env("SEARCH_RATELIMIT", default="60/m")

# django-ratelimit fails CLOSED by default: a cache it cannot reach yields
# `should_limit: True`, i.e. 403 on every rate-limited page at once. The limit
# is a mitigation, not a boundary (docs/01-DESIGN.md §3.6), so a cache outage
# must cost metering, not availability. Set here rather than in prod.py so dev
# and prod cannot diverge on it.
RATELIMIT_FAIL_OPEN = True
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest search/tests/test_people_search_view.py -q`
Expected: PASS (15 passed — the module's 14, plus this one).

- [ ] **Step 5: Correct the stale caching comment**

Still in `config/settings/base.py`, the `# --- Caching ---` block ends with "Still per-process; Redis is the fix (ROADMAP)." That stops being true for prod in Task 2, and the `MAX_ENTRIES` guard now protects only dev and tests. Replace the whole comment above `CACHES`:

```python
# --- Caching ----------------------------------------------------------------
# Explicit only to raise MAX_ENTRIES: LocMemCache defaults to 300 entries and
# culls every 3rd key once past it, which silently evicts *live* rate-limit
# counters — one key per client IP, so ~300 distinct visitors is enough. That
# resets the limit docs/01-DESIGN.md §3.6 names as the real anti-scraping
# mitigation, to zero, under ordinary traffic. Still per-process; Redis is the
# fix (ROADMAP).
```

with:

```python
# --- Caching ----------------------------------------------------------------
# Dev and tests only — prod overrides this with Redis (config/settings/prod.py),
# because LocMemCache is per-process and culls live keys.
#
# MAX_ENTRIES is explicit because LocMemCache defaults to 300 entries and culls
# every 3rd key once past it, silently evicting *live* rate-limit counters (one
# key per client IP, so ~300 distinct visitors is enough). Harmless on a
# single-process runserver; it is why prod may not use this backend.
```

- [ ] **Step 6: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, **422 passed** (421 + 1).

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "fix(settings): a cache outage must cost metering, not availability"
```

---

## Task 2: Redis in production

**Files:**
- Modify: `pyproject.toml` (dependency + `testpaths`)
- Modify: `config/settings/prod.py`
- Create: `config/tests/__init__.py`, `config/tests/test_settings.py`

**Interfaces:**
- Consumes: `RATELIMIT_FAIL_OPEN` from `base.py` (Task 1) — prod inherits it via `from .base import *`.
- Produces: `prod.CACHES["default"]` using `django_redis.cache.RedisCache`; the required env var `REDIS_URL`. Task 3 documents both.

- [ ] **Step 1: Add the dependency and collect the settings tests**

Run: `uv add django-redis`

In `pyproject.toml`, `testpaths` currently reads:

```toml
testpaths = ["accounts", "games", "contributions", "search", "contact"]
```

`config` is absent, so tests under `config/` are never collected. Replace it with:

```toml
testpaths = ["accounts", "games", "contributions", "search", "contact", "config"]
```

- [ ] **Step 2: Write the failing tests**

Create `config/tests/__init__.py` (empty file — the other test packages have one).

Create `config/tests/test_settings.py`:

```python
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
```

- [ ] **Step 3: Run them to make sure they fail**

Run: `uv run pytest config/tests/test_settings.py -q`
Expected: FAIL — `test_prod_refuses_to_start_without_redis` fails because prod imports fine without `REDIS_URL`, and `test_prod_wires_the_cache_to_redis` fails on the `BACKEND` assertion, which still reads `django.core.cache.backends.locmem.LocMemCache` inherited from base.

- [ ] **Step 4: Find out what level django-redis logs at**

Run: `grep -rn "logger\." .venv/lib/python3.12/site-packages/django_redis/cache.py`

Read the result and note the level used when an ignored exception is logged. **Use that level in Step 5's `LOGGING` block.** Do not assume it — the entire point of that block is that a Redis outage reaches a human, and a logger configured above the level django-redis actually uses would swallow it exactly as silently as no logging at all. Record what you found in your report.

- [ ] **Step 5: Wire prod**

In `config/settings/prod.py`, add after the `SECRET_KEY` line:

```python
# --- Cache: Redis ------------------------------------------------------------
# Required, and deliberately fatal when absent. Rate-limit counters live in this
# cache; LocMemCache is per-process and culls live keys, so falling back to it
# would leave a deployment that looks healthy while the anti-scraping mitigation
# docs/01-DESIGN.md §3.6 relies on quietly does not hold.
REDIS_URL = env("REDIS_URL")  # required — crash early if missing

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            # Return None instead of raising when Redis is unreachable. Django's
            # own RedisCache backend catches nothing, so the exception would
            # escape past django-ratelimit's handlers and 500 the request before
            # RATELIMIT_FAIL_OPEN (base.py) could be evaluated. This is the only
            # reason this project depends on django-redis rather than the
            # built-in backend.
            "IGNORE_EXCEPTIONS": True,
        },
    }
}

# Failing open must not mean failing silently: without these, a Redis outage is
# invisible — the same defect, one level up.
DJANGO_REDIS_IGNORE_EXCEPTIONS = True
DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS = True
DJANGO_REDIS_LOGGER = "rollcall.cache"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        # Sentry's SDK captures log records as events; this logger is what makes
        # a swallowed Redis outage visible there and in the PaaS log stream.
        "rollcall.cache": {"handlers": ["console"], "level": "ERROR", "propagate": True},
    },
}
```

Set the `"level"` to whatever Step 4 found. If django-redis logs at `WARNING` rather than `ERROR`, use `"WARNING"` here — and note in your report that Sentry's default logging integration promotes `ERROR` and above to events, so a `WARNING`-level outage would reach the log stream but not Sentry, which is a finding worth surfacing rather than papering over.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest config/tests/test_settings.py -q`
Expected: PASS (2 passed).

- [ ] **Step 7: Confirm dev and tests are untouched**

Run: `uv run pytest search/tests/ accounts/tests/ contributions/tests/ -q`
Expected: PASS. Every existing rate-limit test still runs on `LocMemCache`; if any needed editing, something changed that this plan did not intend — stop and report.

- [ ] **Step 8: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, **424 passed** (422 + 2).

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(settings): Redis for the prod cache, required and loud when it fails"
```

---

## Task 3: Document it, including the trap

The operational half. The retuning warning matters most: the day Redis lands, limits get stricter by the worker count without a number changing, and the resulting 403s look exactly like a regression.

**Files:**
- Modify: `DEPLOY.md`
- Modify: `.env.example`
- Modify: `ROADMAP.md`

- [ ] **Step 1: Add the Redis section to the runbook**

In `DEPLOY.md`, insert a new section between `## 4. Sentry — errors` and `## 4b. GitHub — "Public side projects" block`:

```markdown
## 4c. Redis — rate-limit counters

**Add this with the first deploy, not after it: prod refuses to start without
`REDIS_URL`.**

1. Add Railway's **Redis** plugin to the project. It injects a connection URL —
   expose it to the app service as `REDIS_URL`.
2. That is the whole setup. Prod points `CACHES["default"]` at it automatically.

Why it is required rather than optional: rate-limit counters live in this cache.
The dev/test fallback (`LocMemCache`) is per-process *and* culls live keys once
past `MAX_ENTRIES`, so a limit does not weaken — it silently stops holding. A
graceful fallback would leave a deployment looking healthy while the
anti-scraping mitigation `docs/01-DESIGN.md` §3.6 relies on quietly did not.

**If Redis goes down**, the site stays up and nothing is rate-limited for the
duration (`RATELIMIT_FAIL_OPEN`). The outage is logged to the `rollcall.cache`
logger, so it surfaces in the PaaS log stream and in Sentry rather than passing
unnoticed.

⚠️ **Expect to retune the limits, and do not mistake it for a regression.**
Until now each gunicorn worker counted separately, so `SEARCH_RATELIMIT=60/m`
was really `60/m × workers`. With shared counters it means 60/m — **stricter by
a factor equal to the worker count**, on the day Redis lands, without any number
changing. If 403s appear on a search that worked yesterday, that is the limit
holding for the first time. Both limits are env vars, so retuning needs no
redeploy.
```

- [ ] **Step 2: Drop the stale "before launch" bullet**

In `DEPLOY.md`'s `## 6. Before launch`, delete this bullet entirely — it describes a problem that no longer exists in prod:

```markdown
- Rate limiting uses a per-process in-memory cache (`CACHES` in
  `config/settings/base.py`). Two consequences: each gunicorn worker counts
  separately, and once the cache exceeds `MAX_ENTRIES` it culls keys —
  including live counters, so a limit **silently stops holding** rather than
  merely weakening. `MAX_ENTRIES` is set to 50k to buy headroom; a shared cache
  (Redis) pointed at by `CACHES` is the real fix.
```

Leave the other bullets in that section as they are.

- [ ] **Step 3: Add the variable**

In `.env.example`, add above the `# Anti-scraping rate limits` block:

```
# Redis — rate-limit counters (and the cached Twitch token). REQUIRED in prod:
# config/settings/prod.py refuses to start without it. Unused in dev and tests,
# which use an in-process cache.
REDIS_URL=
```

- [ ] **Step 4: Close the roadmap follow-up**

In `ROADMAP.md`'s `## Known follow-ups (tech debt, not blocking the POC)`, replace this item:

```markdown
- [ ] Rate limiting uses the per-process in-memory cache — add Redis (see DEPLOY.md). Counters are per-worker, and cache culling can evict a live counter, silently resetting the limit; `MAX_ENTRIES` is raised to 50k as an interim guard, Redis removes both problems.
```

with:

```markdown
- [x] **Redis for the rate limit** ✅ (2026-08-12) — prod's cache is Redis, so counters are shared across workers and survive; `REDIS_URL` is required and prod crashes without it, because a silent fallback is exactly the invisibility this fixed. A Redis outage un-meters rather than 500s (`RATELIMIT_FAIL_OPEN` plus django-redis's `IGNORE_EXCEPTIONS` — Django's built-in Redis backend catches nothing, so `RATELIMIT_FAIL_OPEN` would never run behind it) and is logged to `rollcall.cache`. Note the limits are now stricter by the old worker count without any number changing. Spec: `docs/superpowers/specs/2026-08-12-redis-rate-limit-design.md`.
- [ ] `search:suggest` (the nav typeahead) carries no rate limit for anyone, while every other search surface does. It runs three trigram searches per keystroke. Metering it changes behaviour on every page for every visitor, so it needs its own decision rather than a drive-by.
```

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, **424 passed** — docs-only, nothing should move.

- [ ] **Step 6: Commit**

```bash
git add DEPLOY.md .env.example ROADMAP.md
git commit -m "docs: Redis is required in prod; the limits get stricter, not broken"
```

---

## Self-review

**Spec coverage.** Problem and Scope → the whole plan; the out-of-scope `search:suggest` is recorded as a fresh roadmap item in Task 3 rather than built. "The library, and why it is not Django's built-in" → Task 2 Step 1 (the dependency) and Step 5's comment, which states the reason at the call site. "Behaviour when Redis is unreachable" → Task 1 in full. "Failing open must not mean failing silently" → Task 2 Steps 4 and 5, with Step 4 forcing verification of the log level rather than assumption. "Missing configuration in production" → Task 2 Step 5's `env("REDIS_URL")` and its test. "Settings" → Tasks 1 and 2. "The other cache client comes along" → no task: `games/igdb.py` is unchanged by design, and it picks up Redis through `CACHES["default"]` without knowing. "The consequence nobody should misread" → Task 3 Step 1's warning block. "Testing" → the three tests, one in Task 1 and two in Task 2, plus Task 2 Step 7's explicit regression check on the existing suites. "Not doing" → no task touches a rate-limit call site, dev/test settings beyond one flag, `search:suggest`, CI, or a migration.

**Types and names.** `RATELIMIT_FAIL_OPEN` is set in Task 1 and relied on (via inheritance) in Task 2. `REDIS_URL` is introduced in Task 2 Step 5 and documented in Task 3 Steps 1 and 3 under that exact name. `rollcall.cache` is the logger name in Task 2 Step 5 and is referenced in Task 3 Step 1 under the same name. `django_redis.cache.RedisCache` is the string asserted in Task 2 Step 2's test and written in Step 5.

**One thing the implementer must discover rather than copy.** Task 2 Step 4's log level is deliberately not written into this plan: django-redis is not installed until Step 1 of that task, and guessing the level would defeat the section's whole purpose. The step says where to look and what to do with both possible answers.

**Test counts.** The repo is at **421** before Task 1. Task 1 adds 1 → **422**. Task 2 adds 2 → **424**. Task 3 is docs-only → **424**.

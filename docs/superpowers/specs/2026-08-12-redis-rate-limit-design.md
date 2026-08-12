# Redis for the rate limit — a limit that actually holds

> Status: validated 2026-08-12. Behavior source of truth stays
> [docs/01-DESIGN.md](../../01-DESIGN.md), whose §3.6 names the IP rate limit as
> one of exactly three anti-scraping mitigations for the open people search.

## Problem

Rate-limit counters live in `CACHES["default"]`, which is
`LocMemCache` — per process. Two consequences, and the second is the one that
matters:

- **Each gunicorn worker counts separately.** A limit written `60/m` is in
  practice `60/m × workers`. It is not merely weaker than advertised; nobody
  knows by how much, because the multiplier is a deployment detail.
- **`LocMemCache` culls when it exceeds `MAX_ENTRIES`, and culling evicts live
  counters.** A limit does not degrade under load — it **silently stops
  holding**. `MAX_ENTRIES` was raised to 50,000 as an interim guard, which buys
  headroom without changing the failure mode.

[DEPLOY.md](../../../DEPLOY.md) already records this as the one piece of known
tech debt with a security consequence, and `docs/01-DESIGN.md` §3.6 leans on the
IP limit for a search that is open to anonymous visitors. A mitigation that can
stop working without any signal is worse than one known to be weak.

## Scope

Point the production cache at Redis, so counters are shared across workers and
survive. Dev and tests keep `LocMemCache`.

Out of scope: `search:suggest` (the nav typeahead) remains unmetered for
everyone. It runs three trigram searches per keystroke and is a real gap, but
metering it changes behaviour on every page for every visitor and deserves its
own decision. Also out of scope: the paginated sitemap and the `display_name`
btree index, both tracked separately.

## The library, and why it is not Django's built-in

`django-redis`, not `django.core.cache.backends.redis.RedisCache`.

This is forced, not preferred. The decision below is that the site stays up when
Redis is unreachable, and the built-in backend cannot deliver it:

- **django-ratelimit fails *closed* by default.** In `django_ratelimit/core.py`,
  when the cache does not answer it returns `should_limit: True` — 403 on every
  rate-limited view. `RATELIMIT_FAIL_OPEN` inverts that.
- **But `RATELIMIT_FAIL_OPEN` never runs with the built-in backend.** Verified
  against the installed Django 6.0.7: `django/core/cache/backends/redis.py`
  catches no connection error. A `redis.exceptions.ConnectionError` propagates
  past django-ratelimit's `except socket.gaierror` / `except ValueError`
  handlers, so the request 500s before the fallback is ever evaluated. Redis
  down would mean **500 on the home page, every profile, the search and the
  funnel** — not 403.
- **`django-redis`'s `IGNORE_EXCEPTIONS` makes cache operations return `None`**
  instead of raising, which is exactly the shape django-ratelimit's fallback
  expects (`count is None` → fail open).

Cost: one direct dependency, which pulls in `redis`.

## Behaviour when Redis is unreachable

**The site stays up, unmetered, and says so loudly.**

The rate limit is a mitigation, not a security boundary — that is already the
project's stated posture (`docs/01-DESIGN.md` §3.6: the mitigations are the IP
limit, pagination and `profile_public`; the form's ≥1-filter rule is explicitly
*not* a boundary). Taking the whole public site down to avoid a window of
unmetered traffic is the wrong trade.

`RATELIMIT_FAIL_OPEN = True` in `base.py`, so the behaviour is identical in every
environment and cannot diverge between dev and prod.

### Failing open must not mean failing silently

`IGNORE_EXCEPTIONS` alone would make a Redis outage invisible — the same defect
this spec exists to remove, moved one level up. So:

- `DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS = True` and
  `DJANGO_REDIS_LOGGER = "rollcall.cache"`.
- A minimal `LOGGING` block in `prod.py` configures that logger so its records
  are emitted rather than swallowed by Django's default configuration. The
  project has no `LOGGING` block today; this adds the smallest one that does the
  job, not a general logging overhaul.
- Sentry is already initialised in prod, and its SDK enables the logging
  integration by default. **The implementation reads `django_redis`'s source to
  find the level it logs ignored exceptions at, and sets the `LOGGING` block's
  level from what it finds** — not from an assumption. The point of this section
  is that the outage reaches a human; a guessed log level would defeat it as
  surely as no logging at all.

## Missing configuration in production

`prod.py` requires `REDIS_URL` and **crashes at boot without it**, exactly like
`DJANGO_SECRET_KEY` on the line above (`# required — crash early if missing`).

This is deliberate and is the whole point. A silent fallback to `LocMemCache`
would leave the deployment looking healthy while the documented mitigation does
not hold — the precise trap this work removes. The graceful degradation used for
R2, Brevo and Sentry is right for those (the site still does its job without
them); it is wrong here, because the missing piece is invisible from the outside.

Operational consequence, and it is not optional: **the Railway Redis plugin must
be added with the first deploy**, not after it.

## Settings

`base.py` — unchanged default, one addition and one correction:

- `CACHES["default"]` stays `LocMemCache`. Dev and tests are untouched:
  `runserver` is single-process, so the cross-worker problem does not exist
  there, and requiring a Redis for `pytest` would cost every contributor and CI
  a service for no gain.
- Add `RATELIMIT_FAIL_OPEN = True`, with the reasoning beside it.
- The comment above `MAX_ENTRIES` currently says "add Redis in prod for limits
  that hold across workers". It becomes false the moment prod has Redis, and the
  `MAX_ENTRIES` guard now protects only dev and tests. Rewrite it to say that.

`prod.py`:

- `REDIS_URL = env("REDIS_URL")` — required.
- `CACHES["default"]` overridden to `django_redis.cache.RedisCache` with
  `IGNORE_EXCEPTIONS: True`.
- The `DJANGO_REDIS_*` settings and the `LOGGING` block described above.

`.env.example` gains `REDIS_URL` with a one-line note that prod refuses to start
without it.

### The other cache client comes along

`CACHES["default"]` has exactly two consumers: the rate limiter, and the Twitch
OAuth token cached in [games/igdb.py](../../../games/igdb.py). The token rides
along to Redis, and that is a small win rather than a side effect — one token
shared by every worker instead of one fetched per process. Under
`IGNORE_EXCEPTIONS` a Redis outage makes `cache.get` return `None`, so the client
simply fetches a fresh token from Twitch: degraded, not broken. No code in
`games/igdb.py` changes.

## The consequence nobody should misread

Today's limits have been diluted by the worker count. `60/m` has effectively been
`60/m × workers`. Once counters are shared, `60/m` means `60/m`.

**The limits therefore get stricter by a factor equal to the worker count**, on
the day Redis lands, without a single number changing. `SEARCH_RATELIMIT` and
`PROFILE_RATELIMIT` are already env-driven, so retuning needs no deploy — but
this must be written down in `DEPLOY.md`, because the failure it causes looks
exactly like a regression: 403s appearing on a search that "worked yesterday".
It is not a regression. It is the limit holding for the first time.

## Testing

No test may require a running Redis. Three tests cover the three decisions:

| What | How |
|---|---|
| A cache failure does not 403 | Force `cache.add` and `cache.incr` to fail, hit a rate-limited view, assert the response is not 403 — exercising django-ratelimit's fallback branch with `RATELIMIT_FAIL_OPEN` set |
| Prod refuses to boot without `REDIS_URL` | Import the prod settings with the variable unset, assert it raises |
| Prod's cache is wired correctly | Import the prod settings with `REDIS_URL` set, assert `CACHES["default"]` names the django-redis backend and carries `IGNORE_EXCEPTIONS: True` |

Every existing rate-limit test — the focused 403 tests in `search/tests/`,
`accounts/tests/` and `contributions/tests/`, and the `MAX_ENTRIES` eviction test
in `test_people_search_view.py` — keeps running on `LocMemCache`, unmodified.
That is the regression net: if one needs editing, something changed that this
spec did not intend.

The `MAX_ENTRIES` eviction test deserves a note rather than a change. It pins
that "the limit holds under traffic" against `LocMemCache`'s culling. After this
work that scenario is a dev/test-only concern, since prod no longer uses that
backend — but the test stays, because the backend it tests stays.

## Not doing

- No change to any rate-limit call site, key, group or rate value.
- No change to dev or test settings beyond `RATELIMIT_FAIL_OPEN`.
- No metering of `search:suggest`.
- No general logging overhaul — the `LOGGING` block added is the minimum needed
  for the cache logger to be heard.
- No Redis in CI.
- No migration.

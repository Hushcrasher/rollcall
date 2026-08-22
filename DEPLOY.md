# Deploying Rollcall

Target stack (chosen for this POC): **Railway** (app + Postgres + cron),
**Cloudflare R2** (user media), **Brevo** (email), **Sentry** (errors). The app is
a plain Docker image, so none of this is locked in — the same image runs on any
PaaS or a VPS.

> The app deploys and runs without a game catalog. A local dataset is
> available to contributors via `load_dev_fixtures` (DEBUG only). Loading a
> real catalog is a separate step: it needs the operator's own prepared
> parquet matching `games/seed/schema.py`, under the operator's own data
> agreements.

## 1. Railway — app + database

1. Create a new Railway project from the GitHub repo. Railway builds the
   `Dockerfile` (see `railway.json`).
2. Add the **PostgreSQL** plugin. Railway injects `DATABASE_URL` automatically.
3. Set the service **environment variables** (see `.env.example`): at minimum
   `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` (your `*.up.railway.app` domain),
   and `DJANGO_SETTINGS_MODULE=config.settings.prod`.
4. Pick an **EU region** (Metal EU / Amsterdam) for GDPR coherence, and sign
   Railway's DPA (Railway is a US company — see the note in the memory file).
5. Deploy. `railway.json`'s start command runs `migrate` then gunicorn. Static
   files are already collected into the image (whitenoise serves them).
6. The free `*.up.railway.app` subdomain (HTTPS included) is enough for the POC
   — **no custom domain required**.

## 2. Cloudflare R2 — user media

1. Create an R2 bucket (choose the **EU jurisdiction** option).
2. Create an R2 API token → set `S3_BUCKET_NAME`, `S3_ENDPOINT_URL`
   (`https://<accountid>.r2.cloudflarestorage.com`), `S3_ACCESS_KEY_ID`,
   `S3_SECRET_ACCESS_KEY`, `S3_REGION=auto`.
3. When `S3_BUCKET_NAME` is set, prod uses R2 for media automatically. The
   bucket holds avatars (`avatars/`) and the profile gallery (`portfolio/`,
   `portfolio/thumbs/`) — all of them pipeline-produced WebP, never raw
   uploads.
4. The app's 10 MB upload cap (`accounts/images.py`) is checked *after* the
   request body has been received, so it bounds what gets stored, not what
   gets transferred. The platform's own body limit is the first line — Railway
   applies one; if you move off it, set an equivalent limit at the edge.

## 3. Brevo — transactional email

1. In Brevo, create an **SMTP key**.
2. Set `EMAIL_HOST_USER` (SMTP login), `EMAIL_HOST_PASSWORD` (the SMTP key),
   and `DEFAULT_FROM_EMAIL`. Until these are set, prod falls back to console
   email (safe, but nothing is delivered).
3. Verify a sender. A single verified sender is enough to test with a few
   users; a **custom domain + SPF/DKIM** is only needed before onboarding real
   users at scale (deliverability). This is the one task with real lead time.

## 4. Sentry — errors

Set `SENTRY_DSN`. Prod initialises Sentry with `send_default_pii=False`.

## 4b. GitHub — "Public side projects" block

Set `GITHUB_TOKEN` to a **classic Personal Access Token** with the `read:user`
scope (no repo access needed). It is used server-side only for the profile
GitHub block (REST profile + GraphQL contributions). Without it the block is
hidden for profiles that have no cached data yet — the rest of the profile is
unaffected. Rate limit with a token is 5,000 req/h; the cache-aside TTL means a
warm profile view costs zero calls and a daily refresh costs one.

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

**If Redis goes down**, the site stays up and none of the *IP* rate limits are
enforced for the duration (`RATELIMIT_FAIL_OPEN`) — the contact relay's
per-sender limit is backed by the database, not this cache, and keeps holding
(`contact/views.py`, `docs/01-DESIGN.md` §3.6). The outage is logged to the
`rollcall.cache` logger, so it surfaces in the PaaS log stream and in Sentry
rather than passing unnoticed.

⚠️ **Expect to retune the limits, and do not mistake it for a regression.**
Until now each gunicorn worker counted separately, so `SEARCH_RATELIMIT=60/m`
was really `60/m × workers`. With shared counters it means 60/m — **stricter by
a factor equal to the worker count**, on the day Redis lands, without any number
changing. If 403s appear on a search that worked yesterday, that is the limit
holding for the first time. Both limits are env vars, so retuning needs no
redeploy.

## 4d. Verify `REMOTE_ADDR` is the visitor's IP — do this on the first deploy

Every IP rate limit in the app keys on `REMOTE_ADDR` (`django_ratelimit`'s
`key="ip"`). Behind an edge proxy that value can be *the proxy's* address
instead of the visitor's, and then **every visitor shares one counter**:
`SEARCH_RATELIMIT` starts 403-ing strangers for each other's searches, and
`IGDB_RATELIMIT` — 10/m for the whole site — turns the IGDB fallback off under
any real traffic. Since 2026-08-22 that same counter is also what bounds the
funnel's anonymous games-catalogue import, so this is worth five minutes.

The app trusts **no** forwarded header today (`SECURE_PROXY_SSL_HEADER` covers
the scheme only), so the failure direction is *stricter than intended*, never
looser — nothing here is spoofable as it stands. Verify, then decide:

**How to check.** Add `--access-logfile -` to the gunicorn command in
`railway.json` for one deploy and hit the site from a device whose public IP
you know (`curl ifconfig.me`). Gunicorn logs the remote address it sees as the
first field of each line:

```
railway logs | grep 'GET /'
# 203.0.113.7 - - [22/Aug/2026:10:02:11 +0000] "GET / HTTP/1.1" 200 ...  ← the visitor: correct
# 10.0.0.3    - - [22/Aug/2026:10:02:11 +0000] "GET / HTTP/1.1" 200 ...  ← a private/edge address: wrong
```

A private-range or identical-for-everyone address means `REMOTE_ADDR` is the
proxy. Behaviourally the same check without touching the deploy: from two
devices on **different** networks, exhaust `SEARCH_RATELIMIT` on one and search
on the other — a 403 on the second device proves they share a counter.

**If it is the proxy's address.** Do *not* reach for `X-Forwarded-For`
blindly: a client can prepend arbitrary entries, so trusting the leftmost hands
every limit in the app a spoofable key — strictly worse than one shared
counter. Instead, find out how many proxies Railway puts in front of the
service, then set `RATELIMIT_IP_META_KEY` to a callable that takes the entry
**that many hops from the right** of `X-Forwarded-For` (the rightmost entries
are the ones the trusted infrastructure appended; everything left of them is
client-supplied). Verify with the two-device check above before believing it.
Note that Django's own `SECURE_SSL_REDIRECT`/HSTS setup is unaffected either
way — this is only about the rate-limit key.

## 5. Seed the games catalog

Two steps — a **prepare** (join the raw source files into one parquet) and a
**seed** (load that parquet into Postgres):

```
# 1. Joins the operator's normalized source files into one prepared parquet
#    matching games/seed/schema.py. Expects, under --source-dir:
#    igdb/igdb_games.parquet, igdb/igdb_release_dates.parquet,
#    hushcrasher.parquet, steam.parquet
python manage.py prepare_seed_parquet --source-dir data --out data/rollcall_games.parquet
#    → upload data/rollcall_games.parquet to the private R2 bucket.

# 2. Load it into Postgres (reads PARQUET_SOURCE_URL, or --source).
python manage.py seed_games
```

- **`steam.parquet`** is the Steam-derived catalog; that filename is the
  contract `prepare_seed_parquet` expects, whatever the operator's own
  pipeline calls the file upstream.
- **Where the raw files live:** only the *prepared* parquet needs to reach the
  app — put it in the private R2 bucket and point `PARQUET_SOURCE_URL` at it
  (`s3://…` with the S3 creds, or an https URL). The raw source files stay in
  Hushcrasher's data pipeline / R2 and never touch the code repo (they're
  gitignored — `data/`, `*.parquet`).
- The prepared parquet is ~392k games (all IGDB + Steam-only). If the upstream
  files change column names, adjust `games/seed/prepare.py`.
- Set `SEED_ALERT_EMAIL` to be notified on failure. Weekly: a Railway cron
  service can run both commands (prepare then seed), or Hushcrasher's pipeline
  produces the prepared parquet and the cron only runs `seed_games`.
- **Performance:** the bulk loader does the full ~392k catalog in ~2 minutes
  (prepare ~2s + seed ~2min), so both the cold load and the weekly refresh are
  cheap.

## 6. Before launch

- **Rehearse one database restore** from a Railway backup — do it once, for real.
- Review the legal pages (`/terms/`, `/privacy/`) with counsel.
- For ~400k games, switch `sitemap.xml` to a paginated sitemap index.

## Fallback if the schedule slips

Ship the home page's people search — its anonymous-visitor pitch line already
carries the recruiter promise, so there is no separate "For recruiters" page
to build — + contact relay first; advanced recruiter filters can follow a few
weeks later. The candidate-facing promise stays credible either way.

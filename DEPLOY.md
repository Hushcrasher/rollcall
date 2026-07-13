# Deploying Rollcall

Target stack (chosen for this POC): **Railway** (app + Postgres + cron),
**Cloudflare R2** (avatars), **Brevo** (email), **Sentry** (errors). The app is
a plain Docker image, so none of this is locked in — the same image runs on any
PaaS or a VPS.

> ⚠️ **Blocking before real game data goes live:** written IGDB/Twitch + Steam
> ToS confirmation, and the parquet audit (see docs/02-ARCHITECTURE.md §8). The
> app deploys and runs on dev fixtures without any of that; do not ingest real
> scraped game data publicly until the ToS check passes.

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

## 2. Cloudflare R2 — avatars

1. Create an R2 bucket (choose the **EU jurisdiction** option).
2. Create an R2 API token → set `S3_BUCKET_NAME`, `S3_ENDPOINT_URL`
   (`https://<accountid>.r2.cloudflarestorage.com`), `S3_ACCESS_KEY_ID`,
   `S3_SECRET_ACCESS_KEY`, `S3_REGION=auto`.
3. When `S3_BUCKET_NAME` is set, prod uses R2 for media automatically.

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

## 5. Seed the games catalog (after the ToS/parquet prerequisites)

Two steps — a **prepare** (join the raw source files into one parquet) and a
**seed** (load that parquet into Postgres):

```
# 1. Join Hushcrasher's normalized source files into one prepared parquet.
#    Expects, under --source-dir: igdb/igdb_games.parquet,
#    igdb/igdb_release_dates.parquet, hushcrasher.parquet, steamdb.parquet
python manage.py prepare_seed_parquet --source-dir data --out data/rollcall_games.parquet
#    → upload data/rollcall_games.parquet to the private R2 bucket.

# 2. Load it into Postgres (reads PARQUET_SOURCE_URL, or --source).
python manage.py seed_games
```

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
- ⚠️ **Initial cold load is slow** with the current per-row upsert (~50 min for
  the full 392k). See "Known follow-ups" in ROADMAP.md — a bulk-load path is
  the fix. Weekly refreshes (mostly updates) are less affected.

## 6. Before launch

- **Rehearse one database restore** from a Railway backup — do it once, for real.
- Review the legal pages (`/terms/`, `/privacy/`) with counsel.
- Rate limiting uses the default per-process cache. For limits that hold across
  gunicorn workers, add a shared cache (Redis) and point `CACHES` at it.
- For ~400k games, switch `sitemap.xml` to a paginated sitemap index.

## Fallback if the schedule slips

Ship the "For recruiters" page + contact relay first; advanced recruiter
filters can follow a few weeks later. The candidate-facing promise stays
credible either way.

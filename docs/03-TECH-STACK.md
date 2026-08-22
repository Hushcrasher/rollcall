# Tech Stack — Game Industry Credits Platform (POC)

> Companion docs: `01-DESIGN.md`, `02-ARCHITECTURE.md`, `04-DATABASE-SCHEMA.md`.
> Rationale in one line: Python is the team's shared language; the product is a classic relational CRUD app; velocity beats elegance at POC stage.

## Backend

| Component | Choice | Why / notes |
|---|---|---|
| Language | **Python 3.12+** | Team's common language (Hushcrasher is a Python/data shop); one language across app and seed pipeline; accessible to OSS contributors. |
| Framework | **Django 5.x** | Batteries included: ORM, migrations, auth, **auto-generated admin** (recruiter approval + report triage for free), CSRF/session security. The product is exactly Django's home turf. |
| API layer | None in POC | Server-rendered views. If/when a public API is needed: Django REST Framework endpoints beside existing views, no rewrite. |
| Auth | **Django auth** (email+password, email verification, password reset) | Email verification required before creating contributions. No auth SaaS (breaks self-hosting/AGPL spirit). Post-POC: `django-allauth` for Discord OAuth (the industry's network). |
| Templates/front | **Django templates + htmx** (+ optionally Alpine.js for micro-interactions) | No SPA. Native SEO for profile/game pages, session auth, half the work. CSS: Pico CSS v2 classless, vendored (chosen 2026-08-20) + one functional-only app.css; still not architectural — swapping it stays cheap. |
| Image processing | **Pillow** | Two users, one dependency. (1) The avatar/gallery pipeline (`accounts/images.py`): every upload is re-encoded and its EXIF stripped, so no user bytes are served back verbatim. (2) Open Graph card rendering (`cards/`, spec `docs/superpowers/specs/2026-08-21-open-graph-cards-design.md`): server-rendered 1200×630 PNGs for profile/game/site link previews — text only, no illustration, no DB or request in the render path. Pillow ships no usable font, so **Inter** (v4.001, from the github.com/rsms/inter releases, SIL Open Font License 1.1) is vendored under `cards/fonts/` (`Inter-Regular.ttf`, `Inter-Bold.ttf`, `OFL.txt`) rather than pulled at request time. The card's stacked `ROLL`/`CALL` wordmark (spec `docs/superpowers/specs/2026-08-21-search-chrome-design.md`) is the one element set in **JetBrains Mono Bold** instead — a monospace face makes the two four-glyph lines the same width by construction — vendored the same way (v2.304, from the github.com/JetBrains/JetBrainsMono releases, SIL Open Font License 1.1) as `cards/fonts/JetBrainsMono-Bold.ttf` and `OFL-JetBrainsMono.txt`. |
| i18n | Django i18n from day one, `en` only shipped | Cheap discipline now, painful retrofit later. |

## Data

| Component | Choice | Why / notes |
|---|---|---|
| Database | **PostgreSQL 16** (managed by the PaaS) | Already decided at product level; team culture is Postgres. Auto backups; rehearse one restore pre-launch. |
| Search | **Postgres native**: `pg_trgm` (GIN) for typo-tolerant autocomplete; FTS if needed for broader search | No Meilisearch/Elastic at this scale (~400k games). Search code isolated in a `search` module for a future swap. |
| Seed / ingestion | **DuckDB** inside a Django management command | Reads remote parquet natively (HTTP/S3), constant memory, SQL dedup Steam↔IGDB, then batched upserts into Postgres (`ON CONFLICT ... DO UPDATE`). Idempotent. |
| Orchestration | **PaaS scheduled job (weekly cron)** | No Prefect/Airflow/Celery for one weekly job. Command is launcher-agnostic (Prefect-invocable later). Email alert on failure. |
| Migrations | Django migrations, versioned, auto-run on deploy | Dormant tables/columns included from the initial migration. |

## Infrastructure

| Component | Choice | Why / notes |
|---|---|---|
| Hosting | **PaaS — Railway** (EU region; decision overrides the original Scalingo/Clever Cloud default) | Managed Postgres + Redis + cron, Dockerfile deploys. US-owned → EU region + signed DPA (see DEPLOY.md). |
| Packaging | **Dockerfile** for prod, **docker compose** for local dev (app + Postgres) | Anti-lock-in: same image on any PaaS or a VPS. `docker compose up` = contributor onboarding. |
| Object storage | **S3-compatible bucket** via `django-storages` — **Cloudflare R2** chosen (EU jurisdiction; SCCs/DPA to document) | Avatars only in POC (game images served from IGDB/Steam CDNs, never stored). PaaS disk is ephemeral → bucket mandatory. Provider switch = 3 env vars. |
| Email | **Brevo** (alt: Postmark) | Transactional only: verification, reset, contact relay (Reply-To = sender), seed-failure alert. Never raw SMTP. |
| Errors | **Sentry** (free tier) | Only observability beyond PaaS logs in POC. |
| Rate limiting | **django-ratelimit** (IP-based on profiles/search) + DB-backed per-sender limit on contact relay (`contact_requests` table) | Anti-scraping & anti-spam, proportionate to POC. |

## Quality & repo

| Component | Choice | Why / notes |
|---|---|---|
| Repo | Monorepo under the **Hushcrasher GitHub org** | App + seed + infra files + docs + fixtures. |
| License | **AGPL v3** at commit 1 | Deters closed-SaaS forks; relicensing later needs every contributor's consent. |
| Contributions | **DCO** (`Signed-off-by`) | Provenance protection lighter than a CLA. |
| CI | **GitHub Actions**: pytest + **ruff** on every PR | One hour of setup; installs the culture pre-contributors. |
| Tests | **pytest + pytest-django** | Non-negotiable coverage: seed dedup, recruiter search query, account deletion (cascade + anonymization). |
| Fixtures | Loadable fake dataset (a few hundred games, fake profiles) | Contributors have no parquet access. |
| Secrets | Env vars + `.env.example`; never in git history | Parquet URL/creds, IGDB keys, Brevo key, `SECRET_KEY`, S3 creds. |

## Key Python dependencies (indicative)

```
django>=5.0
psycopg[binary]
duckdb                # seed command only
django-storages[s3]
django-ratelimit
django-htmx           # convenience middleware/helpers
pillow                # avatar/gallery pipeline + Open Graph card rendering
whitenoise            # static files from the container
sentry-sdk
gunicorn
pytest, pytest-django, ruff   # dev
# post-POC: django-allauth (Discord), djangorestframework
```

## Environment variables

The canonical, always-current list is **[.env.example](../.env.example)** —
one commented entry per variable. This doc deliberately stops duplicating it
(the two copies had already drifted: Brevo is SMTP `EMAIL_HOST_USER`/
`EMAIL_HOST_PASSWORD`, not the `EMAIL_API_KEY` an earlier revision named).

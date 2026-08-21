# Architecture — Game Industry Credits Platform (POC)

> Companion docs: `01-DESIGN.md` (product decisions), `03-TECH-STACK.md`, `04-DATABASE-SCHEMA.md`.

## 1. Overview

A **single Django monolith** (server-rendered) backed by **one managed PostgreSQL database**, fed weekly by a **batch seed job** reading Hushcrasher's parquet file, deployed as a **Docker container on a PaaS**. Object storage for user avatars. No microservices, no SPA, no dedicated search engine, no message queue.

```
                         ┌─────────────────────────────────────┐
                         │ PaaS (Scalingo or Clever Cloud, EU) │
                         │                                     │
 Users/Recruiters ──────▶│  Django monolith (Docker)           │
                         │   apps: accounts, games,            │
                         │   contributions, search, contact,   │
                         │   cards                             │
                         │        │            │               │
                         │        ▼            │               │
                         │  Managed Postgres   │               │
                         │  (auto backups)     │               │
                         └────────┼────────────┼───────────────┘
                                  │            │
              weekly scheduled job│            ├──▶ S3-compatible bucket (EU) — avatars
              (Django mgmt command│            ├──▶ Transactional email (Brevo) — verification,
               using DuckDB)      │            │     password reset, contact relay, job alerts
                                  ▼            └──▶ Sentry (errors)
                   Hushcrasher parquet (remote, read-only)
                   [fallback: IGDB API, manual at first]

 Game cover images: served directly from IGDB/Steam CDNs — never stored by us.
```

## 2. Core architectural principles

1. **The app's Postgres is autonomous.** The parquet is an upstream batch source. If the server hosting it goes down, the site runs normally; we just miss one refresh. **No application code path ever reads the parquet** — only the seed command does.
2. **Stateful = managed & standard, stateless = containerized.** This is the anti-lock-in rule. Migration to any other PaaS or a VPS = Docker image + `pg_dump` + bucket sync ≈ half a day, rehearsable.
3. **Monolith with clean internal modules** (`accounts`, `games`, `contributions`, `search`, `contact`, `cards`). Search logic isolated in its own module so a dedicated engine could replace Postgres FTS later without a rewrite. `cards` (added 2026-08-21, spec `docs/superpowers/specs/2026-08-21-open-graph-cards-design.md`) is cross-cutting the same way `search` is: it reads `accounts`/`games` models and `search.services.profile_summary()` to render Open Graph card images, but nothing else depends on it back.
4. **Source-owned vs platform-owned data.** Columns imported from the parquet/IGDB are read-only in the app and overwritten on each refresh (the seed script explicitly lists them). Everything else is never touched by the seed. Zero conflicts by construction.
5. **Open-source-fork friendly.** The repo runs without Hushcrasher infrastructure: parquet URL and credentials are env vars; dev fixtures replace the parquet; no Prefect dependency; no proprietary auth service.

## 3. The seed pipeline

- **What:** two steps. **Prepare** (`python manage.py prepare_seed_parquet`, `games/seed/prepare.py`) performs the Steam↔IGDB deduplication/merge in DuckDB SQL over Hushcrasher's raw source files and writes ONE prepared parquet matching the contract in `games/seed/schema.py`. **Seed** (`python manage.py seed_games`) reads that prepared parquet with DuckDB (local/HTTP/S3, constant memory) and bulk-upserts into Postgres (by `igdb_id`, else `steam_appid`). The prepared-parquet contract is the fork boundary: a fork produces a conforming parquet however it likes and never touches prepare.py.
- **Idempotent by design:** first run = initial seed; subsequent runs = weekly refresh. Same code. Rerunnable at will with no damage.
- **Trigger:** the PaaS scheduled job (weekly cron). NOT a Prefect flow on Hushcrasher's VPS — that would couple the app's feeding to external infra and require inbound DB credentials living elsewhere. The command makes **no assumption about its launcher**, so a 5-line Prefect flow can invoke it remotely later if Hushcrasher wants to chain "parquet refresh → app seed".
- **Failure handling:** logs + a simple email alert on failure. No orchestration framework.
- **Data expectations (blocking prerequisites, verify before coding):**
  1. The parquet contains source IDs (`igdb_id`, `steam_appid`) — mandatory for reliable upserts.
  2. A Steam↔IGDB mapping exists (IGDB exposes Steam IDs via `external_games`); otherwise dedup preparation is the first data task, or massive duplicates ensue.
  3. Data agreements in place for each source the operator loads.
- Volume: ~400k games ≈ a few hundred MB in Postgres. Trivial.

## 4. Web application

- **Server-rendered Django templates + htmx** (autocomplete, recruiter filters, small interactions). No SPA in POC: halves the work, gives native **SEO** (profile & game pages indexed — "who worked on X" is a major acquisition channel), and session auth (no JWT).
- **Auth:** Django native (email + password, email verification, password reset). Email verification is **enforced before creating contributions**. Discord OAuth via django-allauth is the first post-POC addition (Discord = the industry's network). **No external auth SaaS** (would break self-hosting).
- **Admin:** Django admin serves as the back-office for recruiter application approval, report triage, and manual game additions. Free.
- **Search:**
  - Autocomplete & name search: `pg_trgm` + GIN indexes (typo-tolerant: "hade" → "Hades").
  - Recruiter search: pure SQL — join `contributions × games × game_engines/game_genres` with composite indexes. No external search engine.
- **Contact relay:** form → transactional email to the target person, **Reply-To = sender's address**; the target's email is never exposed. Per-sender rate limiting backed by the `contact_requests` table (also the abuse audit trail).
- **i18n:** all strings through Django's i18n from day one; only `en` shipped in POC.

## 5. Infrastructure & operations

| Concern | Decision | Notes |
|---|---|---|
| Hosting | **PaaS: Railway** (EU region) — decision 2026, overriding the original Scalingo/Clever Cloud default | Railway is US-owned: pick the EU region and sign the DPA (see ROADMAP prerequisites + DEPLOY.md). |
| Deployment | **Dockerfile** (not buildpacks) | Same image runs anywhere. `compose.yml` for local dev shares the base. |
| Database | Managed Postgres on the PaaS | Automatic backups. **Rehearse one restore before launch.** Exit = `pg_dump`. |
| Object storage | S3-compatible bucket via django-storages — **Cloudflare R2** chosen (EU jurisdiction option, SCCs/DPA to document) | Avatars only in POC. Switching provider = 3 env vars. PaaS disk is ephemeral → bucket required from the first avatar. |
| Scheduled jobs | PaaS scheduler → mgmt commands | Weekly seed. No Celery/queue in POC. |
| Email | **Brevo** (or Postmark) | Never raw SMTP from the server. Free tier fine for POC. |
| Errors | Sentry (free tier) | No metrics/dashboard stack in POC. |
| Rate limiting | django-ratelimit (per IP) on profile pages & search; per-account on contact relay | Anti-scraping: make mass extraction costly; emails are unreachable by design. |
| Scraping posture | No exhaustive paginated "all people" endpoint; profiles reached via search or game pages. robots.txt allows profile indexing (we want SEO), controlled sitemap. | Public pages can't be fully protected — accept and mitigate. |
| Secrets | Env vars + documented `.env.example`; never in git history | Parquet URL/credentials, IGDB keys, email API key, Django secret. |

## 6. Repository (open source under the Hushcrasher GitHub org)

- **Monorepo:** Django app + seed command + `Dockerfile` + `compose.yml` (Postgres for local dev) + dev fixtures + docs.
- **License: AGPL v3 in `LICENSE` at commit 1** (relicensing after external contributions requires every contributor's consent).
- **DCO** (`Signed-off-by`) instead of a CLA: minimal provenance protection without scaring contributors.
- README transparency paragraph: *"Code is AGPL; the production database is operated by Hushcrasher."*
- **Dev fixtures:** a few hundred fake/sample games + fake profiles, loadable in one command (refuses to run outside `DEBUG`) — contributors have no parquet access; without fixtures nobody can contribute.
- **CI (GitHub Actions) from the start:** tests + ruff on every PR.
- Public/private boundary: all *code* is public including the seed logic; parquet URL, credentials, and DB dumps are private. A fork must be able to plug its own game source — that's the cleanliness test.

## 7. Testing & quality — the minimal kit

No coverage dogma, but three non-negotiable zones:
1. **Seed script** — especially Steam↔IGDB dedup (where data rots silently).
2. **Recruiter search query** — it *is* the product promise.
3. **Account deletion** — cascade + vouch anonymization: a legal obligation; a bug here is severe.

Migrations: Django's, versioned, auto-applied on deploy. Dormant tables/columns ship in the initial migrations.

## 8. Pre-code checklist (blocking)

1. Data agreements in place for each source the operator loads.
2. Parquet content audit: source IDs present, Steam↔IGDB mapping exists.
3. Open accounts: PaaS, bucket, Brevo, Sentry; pick Scalingo vs Clever Cloud.

## 9. Deliberate non-choices (and their triggers)

| Not doing | Would reconsider when |
|---|---|
| Microservices | Never at foreseeable scale |
| SPA / public API | Product traction → versioned DRF API alongside views (no rewrite; SvelteKit skills exist in-house for richer front-ends) |
| Dedicated search engine (Meilisearch…) | Search relevance becomes the product; module isolation makes the swap contained |
| Celery / task queue | First genuinely async need (bulk emails, heavy jobs) |
| Prefect integration | Hushcrasher wants pipeline chaining; command is already invocable |
| Metrics stack | Post-POC |

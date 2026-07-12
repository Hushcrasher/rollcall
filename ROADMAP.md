# Rollcall — POC Roadmap

> Living tracking document. Check items off as they land; add notes/dates inline.
> Behavior source of truth: [docs/01-DESIGN.md](docs/01-DESIGN.md) · Build order from [docs/00-README.md](docs/00-README.md).
> When starting a phase, write a detailed implementation plan for it first (tasks, tests, code) — this file tracks *what*, the phase plans define *how*.

**Status legend:** `[x]` done · `[ ]` to do · ⚠️ blocked on something external

---

## Blocking prerequisites (external — before the seed phase)

These do not block Phases 0–1, but **must be resolved before coding the seed** (Phase 2):

- [ ] ⚠️ Written confirmation that IGDB/Twitch ToS cover this use (Hushcrasher-backed public product) — same check for Steam-derived data
- [ ] ⚠️ Parquet audit: `igdb_id` / `steam_appid` present; Steam↔IGDB mapping available (else dedup prep is the first data task)
- [ ] ⚠️ Accounts opened: PaaS (pick Scalingo vs Clever Cloud), S3-compatible bucket (EU preferred: Scaleway), Brevo, Sentry

---

## Phase 0 — Repo bootstrap ✅

Goal: a Django skeleton that runs, with license, CI and containers in place.

- [x] uv project, Python 3.12, dependencies from [docs/03-TECH-STACK.md](docs/03-TECH-STACK.md)
- [x] Django project (`config/` with base/dev/prod/test settings, env-driven)
- [x] Apps created: `accounts`, `games`, `contributions`, `search`, `contact` ([docs/02-ARCHITECTURE.md](docs/02-ARCHITECTURE.md) §2.3)
- [x] **Custom user model** (email as login identifier) defined *before any migration* — cannot change later
- [x] i18n wired from day one (`LocaleMiddleware`, `LANGUAGES=[en]`, `locale/`)
- [x] `Dockerfile` (prod image, whitenoise static) + `compose.yml` (app + Postgres 16)
- [x] CI: GitHub Actions — ruff + ty + pytest on every push/PR
- [x] Coding rules: Python fully typed, Astral stack (uv, ruff, ty) — enforced via ruff `ANN` rules and `ty check` in CI
- [x] `LICENSE` = AGPL v3 (must be in the **first commit**)
- [x] `.env.example` with every secret/endpoint; `.gitignore` excludes `.env`
- [x] README with transparency paragraph (AGPL code / private Hushcrasher DB) + CONTRIBUTING with DCO
- [x] Initial commit — **LICENSE included in it** (AGPL v3: code only; user data stays private under Hushcrasher)
- [x] Repo created on GitHub (`Micro-SAS/rollcall`) and pushed

## Phase 1 — Database schema & fixtures ✅

Goal: the **complete** schema from [docs/04-DATABASE-SCHEMA.md](docs/04-DATABASE-SCHEMA.md), dormant parts included, in the initial migrations.

- [x] `pg_trgm` extension migration (`TrigramExtension`, first operation of `accounts/0001`)
- [x] `accounts`: User migration (GIN trgm index on `display_name`) + `RecruiterApplication` (§2)
- [x] `games`: `Game` (§3, incl. dormant `parent_game_id`), `Genre`/`Engine` + M2M link tables (§4), `Company` + dormant `CompanyAlias`/`claimed_by` (§5), `GameCompany` (§6) — GIN trgm indexes on `title`, `name`, `alias`
- [x] `contributions`: `Discipline` (§7) + **data migration seeding the 11 disciplines** · `Contribution` (§8: CASCADE user, PROTECT game/discipline, SET NULL company, CHECK `end_date >= start_date`, month/year dates as DATE day=01, dormant `status`) · dormant `Vouch` (§9, nullable `voter_id`, ships empty)
- [x] `contact`: `ContactRequest` (§10) + `Report` (§11) — nullable/SET NULL sender & reporter FKs
- [x] Composite indexes for the recruiter query: `(discipline_id, game_id)` etc. (§8)
- [x] Django admin registrations ([source] columns read-only for seeded rows)
- [x] **Dev fixtures**: `manage.py load_dev_fixtures` — 300 fake games, 50 companies, 40 profiles, 150 contributions; deterministic & idempotent
- [x] Tests (20): CHECK constraints, cascades/anonymization on account deletion, vouch uniqueness, trigram search, fixtures idempotency

## Phase 2 — Seed pipeline (⚠️ gated on the prerequisites above)

Goal: `python manage.py seed_games` — idempotent weekly refresh, DuckDB → Postgres.

- [ ] DuckDB reads the remote parquet (HTTP/S3, `PARQUET_SOURCE_URL`), constant memory
- [ ] Steam↔IGDB dedup/merge in SQL
- [ ] Batched upserts: `ON CONFLICT (igdb_id) DO UPDATE`, by `steam_appid` for Steam-only rows; companies by `igdb_company_id`
- [ ] Write-surface strictly limited to `[source]` columns (§13) — never platform-owned data; upstream deletions never delete locally
- [ ] Genres/engines/game_companies link tables populated from IGDB taxonomies
- [ ] Failure handling: logs + email alert; launcher-agnostic (PaaS cron now, Prefect-invocable later)
- [ ] **Tests on dedup** (non-negotiable zone #1) — fixture parquets covering: IGDB-only, Steam-only, both-linked, conflicting rows, re-run idempotency

## Phase 3 — Accounts

Goal: the full account lifecycle, GDPR included.

- [ ] Signup (email + password, free display name) with clear consent copy: *"Your profile and credits will be public and accessible to recruiters — that is the point of the platform."*
- [ ] Email verification flow (Brevo transactional API — never raw SMTP); **gate: no contribution creation before verified**
- [ ] Login / logout / password reset
- [ ] Profile page (`/{slug}`) honoring `profile_public`
- [ ] Settings: the 3 visibility booleans — `contactable` toggle easy to find (ease of exit, no dark pattern)
- [ ] Avatar upload to the S3 bucket (django-storages)
- [ ] **Account deletion** (non-negotiable zone #3): contributions CASCADE, vouches emitted → `voter_id` SET NULL, contact_requests/reports SET NULL, avatar object deleted — with tests
- [ ] **JSON export** of personal data (identity, credits, vouches emitted, contacts) — with tests

## Phase 4 — Contributions & public pages

Goal: the core loop — declare a contribution, see it on person and game pages.

- [ ] Contribution create/edit/delete: game autocomplete (pg_trgm, htmx), optional employer company, discipline select, free job title, month/year dates (open end) — game required in POC forms
- [ ] Multiple contributions per (person, game) allowed
- [ ] Person page: credits list with dates (only `status='active'`)
- [ ] Game page: contributors list (same table read the other way) + IGDB/Steam CDN cover
- [ ] Company page: aggregation only (games from IGDB facts, contributors via contributions)
- [ ] "Declared" badge on unconfirmed contributions (vouching itself stays out of POC)

## Phase 5 — Simple search

Goal: find games and people, open to all.

- [ ] Games/people search on `pg_trgm` (typo-tolerant: "hade" → "Hades"), isolated in the `search` app
- [ ] Autocomplete endpoints (htmx) reused from Phase 4
- [ ] No exhaustive "all people" paginated endpoint (anti-scraping posture)

## Phase 6 — Recruiter side

Goal: the full two-sided loop the POC must test.

- [ ] Recruiter application form (name, company, work email, LinkedIn) → `pending`
- [ ] Manual approval in Django admin → sets `role='recruiter'`
- [ ] **Recruiter search** (non-negotiable zone #2): discipline × engine × genre × rating (`steam_positive_pct` / IGDB fallback) × dates × `open_to_work`, honoring `profile_public` — **with tests on the query** (it is the product promise); rating never a default sort; 2D/3D filter best-effort or deferred, never blocking
- [ ] **Contact relay**: form → email to the target (if `contactable`), Reply-To = sender, recipient email never in any page/response; per-sender rate limit backed by `contact_requests` (with tests)
- [ ] Public "For recruiters" page — honest copy, no inflated counters

## Phase 7 — Hardening & launch prep

Goal: legally and operationally ready for real users.

- [ ] Report/flag form (logged-in, target type + reason) + admin triage
- [ ] Rate limiting: django-ratelimit (IP) on profile pages & search
- [ ] robots.txt (allow profile indexing — SEO is an acquisition channel) + controlled sitemap
- [ ] Sentry wired in prod (`send_default_pii=False`)
- [ ] Deploy to the PaaS: managed Postgres, scheduled weekly `seed_games` job, env vars set
- [ ] **Rehearse one Postgres backup restore** before launch
- [ ] Legal pages: ToS (non-exclusive data license, no open-data promise), privacy policy, signup consent copy reviewed
- [ ] Fallback if schedule slips: ship "For recruiters" page + contact relay first, advanced filters later

---

## Deliberately NOT in the POC

Vouching UI (schema ships dormant) · company claim · manual game creation · internal messaging · payments · automated recruiter verification · moderation workflow beyond the report form · sub-disciplines · skills · Discord OAuth (first post-POC addition) · public API.

## Success metric (from docs/01-DESIGN.md §4)

1. Industry people, not individually solicited, create an account and declare ≥1 complete contribution.
2. A few real recruiters apply, get approved, run searches, and send contact requests.

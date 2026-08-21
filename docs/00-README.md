# Docs pack — Game Industry Credits Platform (POC)

Documentation set for implementation (intended to be handed to Claude Code).

| File | Content |
|---|---|
| `01-DESIGN.md` | Product vision, all validated design decisions, POC scope, success metrics. **Read first — it is the source of truth for behavior.** |
| `02-ARCHITECTURE.md` | System architecture, seed pipeline, infrastructure, repo/OSS setup, testing priorities. |
| `03-TECH-STACK.md` | Exact technology choices with rationale, dependencies, env vars. |
| `04-DATABASE-SCHEMA.md` | Table-by-table schema, constraints, indexes, deletion/GDPR behavior, seed write-surface. |

## Non-negotiables (if in doubt, these win)

1. Personal emails are **never** displayed or exposed anywhere. Contact only via relay (Reply-To pattern).
2. The app's Postgres is autonomous; **no application code reads the parquet** — only the seed management command.
3. Seed-owned columns are read-only in the app; the seed never writes platform-owned data (see `04`, §13).
4. Internal IDs are the pivot; external IDs are nullable+unique.
5. Account deletion must fully work in the POC: contributions cascade, vouches anonymized, JSON export available.
6. Email verification required before creating a contribution. *Scoped relaxation (2026-08-11): the declare funnel may write a `pending` row before verification — nothing unverified is ever **published**; `/credits/new/` keeps the full gate. See `01-DESIGN.md` §3.3.*
7. No public negative signals of any kind (no down-votes, no public "disputed", no numeric trust scores).
8. AGPL v3 license file in the first commit; secrets only in env vars, never in git history.
9. Dormant schema (vouches, statuses, claimed_by, parent_game_id, aliases) ships in the initial migrations, with no UI.
10. UI in English, all strings through Django i18n.

## Blocking prerequisites before coding the seed

1. Data agreements in place for each source the operator loads.
2. Parquet audit: `igdb_id` / `steam_appid` present; Steam↔IGDB mapping available (else dedup prep first).
3. Accounts opened: PaaS, S3-compatible bucket, Brevo, Sentry. *(Chosen stack — see ROADMAP.md and DEPLOY.md: Railway + Cloudflare R2, EU regions + DPAs; this overrides the Scalingo/Scaleway defaults named in `02`/`03`.)*

## Suggested build order

1. Repo bootstrap: Django project, custom user model (⚠️ before any migration), Docker/compose, CI, LICENSE, `.env.example`.
2. Initial migrations: full schema from `04-DATABASE-SCHEMA.md`, including dormant parts; discipline data migration; dev fixtures.
3. Seed management command (DuckDB → upsert) + tests on dedup.
4. Accounts: signup, email verification, profile page (3 visibility booleans), account page, account deletion + JSON export.
5. Contributions CRUD (game autocomplete via trigram, company optional, dates month/year) + person page + game page.
6. Simple search (games/people).
7. Recruiter side: application form + admin approval, recruiter search with filters + tests on the query, contact relay + rate limit. The search is the home page and is itself the recruiter-facing surface; its anonymous-visitor pitch line carries the promise a separate "For recruiters" page used to.
8. Report form, rate limiting, robots/sitemap, Sentry.

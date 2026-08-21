# Rollcall — POC Roadmap

> Living tracking document. Check items off as they land; add notes/dates inline.
> Behavior source of truth: [docs/01-DESIGN.md](docs/01-DESIGN.md) · Build order from [docs/00-README.md](docs/00-README.md).
> When starting a phase, write a detailed implementation plan for it first (tasks, tests, code) — this file tracks *what*, the phase plans define *how*.

**Status legend:** `[x]` done · `[ ]` to do · ⚠️ blocked on something external

---

## Blocking prerequisites (external — before the seed phase)

These do not block Phases 0–1, but **must be resolved before coding the seed** (Phase 2):

- [x] Data agreements: IGDB/Twitch confirmed 2026-08-04.
- [ ] ⚠️ Parquet audit: `igdb_id` / `steam_appid` present; Steam↔IGDB mapping available (else dedup prep is the first data task)
- [~] ⚠️ Accounts opened (chosen stack overrides docs' Scalingo/Scaleway defaults): **Railway** (PaaS — account created), **Cloudflare R2** (storage — bucket TODO), **Brevo** (account created; DNS/domain auth deferred to Phase 7), **Sentry** (TODO). None needed before Phase 7. GDPR: Railway + R2 are US → pick EU regions + sign DPAs.

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

## Phase 2 — Seed pipeline ✅ (engine built; ⚠️ real-parquet wiring still gated)

Goal: `python manage.py seed_games` — idempotent weekly refresh, DuckDB → Postgres.

Built test-first against a **documented assumed parquet schema** (`games/seed/schema.py`) — the contract a fork or the real Hushcrasher parquet must match. Pointing it at the real source later = adjust column names in `schema.py` + clear the prerequisites above.

- [x] DuckDB reads the parquet (local path, or HTTP/S3 via httpfs, `PARQUET_SOURCE_URL`), constant memory (`fetchmany` streaming)
- [x] Steam↔IGDB dedup/merge in SQL — now lives in the **prepare step** (`games/seed/prepare.py`, `prepare_seed_parquet`); `pipeline.py` is a straight reader of the prepared parquet
- [x] Idempotent upserts: by `igdb_id`, else `steam_appid`; companies by name
- [x] Write-surface strictly limited to `[source]` columns (§13) — slug/contributions preserved; upstream deletions never delete locally
- [x] Genres/engines/game_companies link tables populated + reset from source each run
- [x] Failure handling: logs + optional email alert (`SEED_ALERT_EMAIL`); launcher-agnostic (`--source` arg for Prefect later)
- [x] **Tests on dedup** (non-negotiable zone #1): IGDB-only, Steam-only, both-linked merge, dedup-within — plus upsert idempotency/write-surface and end-to-end command tests (23 seed tests)
- [ ] ⚠️ Adjust `schema.py` column names to the operator's prepared parquet + wire `PARQUET_SOURCE_URL` in prod
- [ ] ⚠️ Schedule the weekly `seed_games` job on the PaaS (Phase 7 deploy)

## Phase 3 — Accounts ✅

Goal: the full account lifecycle, GDPR included. Built TDD (32 account tests).

- [x] Signup (email + password, free display name) with clear consent copy + required consent checkbox
- [x] Email verification flow (console backend in dev; single-use replay-safe token). **Gate helper ready** (`user.is_email_verified`) — enforced on contribution create in Phase 4. Brevo API wired in Phase 7
- [x] Login (by email) / logout / password reset (Django's flow + our templates)
- [x] Profile page at `/u/<slug>/` honoring `profile_public` (private → 404 for others); **email never rendered**
- [x] Settings: the 3 visibility booleans — `contactable` toggle plainly present
- [x] Avatar upload (`ImageField` → default storage in dev, R2 in prod)
- [x] **Account deletion** (non-negotiable zone #3): confirm → cascade contributions, anonymize vouches, delete avatar file, logout — with tests
- [x] **JSON export** of personal data (identity, settings, credits, vouches, contacts) — with tests
- [x] Verified end-to-end in the browser: signup → verification email → verified → settings → profile (no email leak)

## Phase 4 — Contributions & public pages ✅

Goal: the core loop — declare a contribution, see it on person and game pages. Built TDD (27 tests); verified end-to-end in the browser.

- [x] Contribution create/edit/delete: game autocomplete (pg_trgm, htmx, vendored locally), optional employer company (autocomplete), discipline select, free job title, month/year dates (`<input type=month>` → DATE day=01, open end) — game required in POC forms; owner-only edit/delete
- [x] Multiple contributions per (person, game) allowed
- [x] Person page: active credits list with dates + "present" for open end; owner Add/Edit/Delete controls
- [x] Game page: contributors list (same table read the other way) + IGDB/Steam CDN cover + genres/engines/dev-pub; **email never leaked**
- [x] Company page: aggregation only (games from IGDB `game_companies` facts, contributors via contributions)
- [x] "Declared" badge on every contribution (vouching stays out of POC)
- [x] **Email-verified gate** enforced on create (design non-negotiable #6); only `status='active'` shown anywhere
- [x] Trigram autocomplete lives in the isolated `search` module (reused by Phase 5)

## Phase 5 — Simple search ✅

Goal: find games and people, open to all. Built TDD (9 tests); verified in the browser.

- [x] Games/people search on `pg_trgm` (typo-tolerant: "kojma" → "Hideo Kojima"), isolated in the `search` app
- [x] `search_people` never surfaces `profile_public=False` users (anti-exposure) — verified live
- [x] Public `/search/?q=` results page (games + public people) + header search box; **email never leaked**
- [x] Autocomplete endpoints (htmx) shared with Phase 4's contribution form
- [x] No exhaustive "all people" listing — a blank query returns nothing (anti-scraping posture)

## Phase 6 — Recruiter side ✅

Goal: the full two-sided loop the POC must test. Built TDD (27 tests); the whole loop verified in the browser (apply → approve → search → contact).

- [x] Recruiter application form (name, company, work email, LinkedIn) → `pending`; one pending per user
- [x] Manual approval via Django admin action → `RecruiterApplication.approve()` sets `role='recruiter'`, `reviewed_by`/`reviewed_at`
- [x] **Recruiter search** (non-negotiable zone #2): discipline × engine × genre × rating (`steam_positive_pct` **or** IGDB) × `year_from` × `open_to_work`, honoring `profile_public`, only `status='active'` — every filter crosses within a SINGLE contribution; **8 query tests + view tests**; rating never a sort (order by display_name); gated to recruiters — **superseded 2026-07-16: the search is now open to all**, see Post-roadmap additions
- [x] **Contact relay**: form → email to the target (only if `contactable`), Reply-To = sender, recipient email never in any page/response — verified live; per-sender 24h rate limit backed by `contact_requests` (with tests); can't contact self
- [x] Public "For recruiters" page — honest **real** counts (no inflation), apply CTA
- [x] 2D/3D filter: deferred per docs (no direct IGDB field) — not blocking

## Phase 7 — Hardening & launch prep

Goal: legally and operationally ready for real users. Buildable pieces done TDD (11 tests); deploy is documented and awaits the external prerequisites.

- [x] Report/flag form (logged-in, target type + optional id + reason) + report links + admin triage; verified in the browser
- [x] Rate limiting: django-ratelimit (IP) on profile pages & search (settings-driven; disabled in tests except a focused 403 test)
- [x] robots.txt (allows `/u/ /g/ /c/`, disallows private areas) + `sitemap.xml` (public profiles + games + companies; private profiles excluded)
- [x] Home page at `/` (no more root 404); legal pages linked in the footer
- [x] Sentry wired in prod (`send_default_pii=False`) — already in `config/settings/prod.py`
- [x] Deploy **config prepared**: `railway.json` (migrate on release), Dockerfile binds `$PORT`, prod Brevo SMTP backend (console fallback), R2 media, `.env.example` updated, **DEPLOY.md** with the full runbook
- [x] Legal pages: ToS (non-exclusive data license, no open-data promise, AGPL) + privacy (GDPR rights, EU hosting) — POC drafts, flagged for counsel review
- [ ] ⚠️ **Execute the deploy** (Railway/R2/Brevo/Sentry accounts) — manual; see [DEPLOY.md](DEPLOY.md)
- [ ] ⚠️ **Rehearse one Postgres backup restore** before launch — manual
- [ ] ⚠️ Weekly `seed_games` cron — after the prepared parquet is in place
- [x] Fallback documented (DEPLOY.md): ship "For recruiters" + contact relay first if the schedule slips

## Phase 8 — Mobile-first surface ✅ (spec 2026-08-20)

Goal: a styled, mobile-first site without custom design — Pico CSS v2 classless.

- [x] Pico CSS v2 classless vendored; `app.css` = functional layout only (dark mode fixed)
- [x] Nav: ROLLCALL wordmark, `Add your credit` primary CTA (declare funnel for anonymous)
- [x] Home: filters first for everyone; worker pitch = one-line banner; `#results` anchor
- [x] Latest-credits feed (active credits of public profiles only)
- [x] Credit dates display as MM/YYYY sitewide
- [x] About page (`/about/`) — mission, data provenance, AGPL, safety
- [x] English copy pass (canonical CTA, year-filter label)

## Phase 9 — Profile gallery & upload hardening ✅ (spec 2026-08-20)

Goal: artists can show work; every upload goes through one hardened pipeline.

- [x] `accounts/images.py`: re-encode to WebP, EXIF stripped, SVG/GIF impossible, 10 MB + 40 MP caps, UUID names
- [x] `ProfileImage` (migration 0007): 12 max, captions, newest first; admin registered
- [x] Upload/delete views — verified-only, rate-limited (10/h), owner-only delete
- [x] "Work" section on profiles (after credits); grid layout in app.css
- [x] Avatar routed through the same pipeline (512px)
- [x] GDPR: deletion removes files; JSON export lists the portfolio

## Post-roadmap additions

- [x] **Dev email backend** — prints a clean, copy-friendly body so console verification/reset links aren't corrupted by quoted-printable wrapping
- [x] **IGDB live fallback** (docs §3.1): `games/igdb.py` client (Twitch OAuth, cached token) + `import_igdb_game` (reuses the seed upsert, `source=igdb_live`) + login-gated search/import endpoints, folded inline into the credit-form game search as a "Not it? Search IGDB" option (local-first; IGDB only on deliberate click — rate-friendly). Hidden unless `IGDB_CLIENT_ID`/`SECRET` are set. Verified live end-to-end.
- [x] **Live search everywhere**: nav bar typeahead dropdown (`/search/suggest/`) over games + people + companies; the full search page and nav both match companies now
- [x] **Open recruiter search** (2026-07-16): the search is open to everyone, anonymous included — the `RecruiterRequiredMixin` is deleted and the apply/approve flow goes dormant (still works, gates nothing). Multi-select engines/genres + person-level country filter (`User.country`, django-countries) via an htmx typeahead with chips (which replaced 249 country checkboxes — 34,908 bytes → 822 on every anonymous hit). Rich result cards: matching credits, "City · Country", career stats, labelled engine repartition %. Pagination preserving filters. Mitigations are the IP rate limit + pagination + `profile_public`; the form's ≥1-filter rule is a UX guard, **not** an anti-enumeration boundary (docs/01-DESIGN.md §3.6). robots.txt now Allows the `/search/for-recruiters/` promise page while keeping the filter search disallowed. Spec: `docs/superpowers/specs/2026-07-16-open-recruiter-search-design.md`.
- [x] **Profile / Account split** (2026-08-04): the eight profile fields + GitHub URL move from `/settings/` to `/profile/edit/`; `/settings/` becomes `/account/` and keeps only email verification, JSON export and account deletion. A slugless `/profile/` resolves `LOGIN_REDIRECT_URL`, which now lands members on their own profile (a plain string setting can't pass a slug to `reverse()`). The profile page gains **View as member** (`?preview=member`, owner-only — for anyone else the param is inert; owner controls hidden and Contact/Report rendered as inert `<span>`s, since contacting yourself is refused by the relay) and a neutral **private-profile notice**: `profile_public=False` hides a member everywhere while `_visible_users` keeps showing them their own page, a silent state nothing else surfaced. The notice states the fact with a quiet link and does not push to reverse the setting — the flag is a safety valve. No migration. Verified in the browser, avatar upload included (the form's `enctype` is load-bearing and no test can catch it). Spec: `docs/superpowers/specs/2026-08-04-profile-account-split-design.md`.
- [x] **Constrained employer field**: picking a game loads its studios as quick-picks (`/games/<pk>/employers/`), with a "Worked for another company?" live search and a "Not there? Create '<name>'" path (`/companies/create/`, `source=manual`) for outsourcing studios missing from IGDB
- [x] **The home page becomes the people search** (2026-08-11): `/` served a menu of four links that were all reachable from the nav bar anyway; it now serves the open people search directly, under the same URL name `home` (a view move, not a redirect, so `{% url 'home' %}` keeps resolving). The "For recruiters" promise page and the old landing are deleted outright — 404, no redirect, since nothing indexed points at either and the site is not deployed. Anonymous visitors get one pitch line plus a signup link above the form; members get the tool alone — **superseded 2026-08-20: the pitch line now reads "Worked on a game? Add your credit — no account needed to start." and links to the declare funnel at `/declare/`, not to signup directly**, see Phase 8 above. Two consequences carried the real work: the combinatorial filter-URL space moved to the root, where a path prefix cannot close it (`Disallow: /` would delist the site), so it is closed by query string with `Disallow: /*?` — honoured by Google and Bing, ignored by `urllib.robotparser`, with a `rel=canonical` as the second layer; and the IP rate limit had to stop applying to the bare page, or one office behind a single NAT would turn the front door into a 403 (quota is now spent only by requests carrying a query string). The nav box, now the only route to game/company lookup, says so: "Search games, companies and people". The recruiter application flow stays routed but unlinked. No migration. Spec: `docs/superpowers/specs/2026-08-11-home-is-people-search-design.md`.
- [x] **Deferred registration funnel** (2026-08-11): the home page asks "which game did you work on?" before it asks for anything else; the visitor fills a complete credit and creates the account at the end. The load-bearing discovery is that `SignupView` already auto-logs-in, so the account exists before the verification mail is opened — the credit becomes a row at signup with a new `Contribution.Status.PENDING` and is published by `verify_email`, which means verifying from a phone two days later works. Steps 1–3 hold raw form strings in the session (the session serializer is JSON, so `date` objects can't go there) and re-validate through `ContributionForm` before saving. The anonymous root leads with the question, so crawlers now index the home page under it — accepted knowingly — **superseded 2026-08-20: the question moved off the home page to its own `/declare/` URL; the home page now indexes under the recruiter-facing search question instead**, see Phase 8 above. `igdb_search`, `igdb_import` and `company_create` stay `@login_required`: a game missing from the catalogue converts into a signup rather than opening a write endpoint to anonymous traffic. One migration. Spec: `docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md`.
- [ ] **Referral loop** (deferred 2026-08-11, no spec yet): let a member name colleagues they worked with so Rollcall can invite them. Build the version where the invitation link lands the invited person on a *pre-filled* credit form — the data is shown only to the person it describes. Do **not** build the variant that publishes a "pending credits" list on game and company pages: a game page is public, so hiding it from search and the sitemap does not contain it, and it contradicts the rule that nobody writes another person's credit. Prerequisites: GDPR Article 14 handling and counsel review, a per-sender send limit like the contact relay's, a claim channel (pending entries without an email have none, so they shouldn't exist), and person-record dedup. Reasoning recorded in `docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md` §Deferred.

- [x] **Project review fixes** (2026-08-12, from `docs/reviews/2026-08-12-project-review.md`): fresh-clone Docker build repaired (collectstatic placeholder `REDIS_URL` + a CI `docker build` job + `.dockerignore` keeping `.env`/parquets out of image layers); dev settings tolerate a verbatim `cp .env.example .env`; **emails are case-folded** at signup/login/manager with a `Lower(email)` unique constraint (migration `accounts/0006`); **the contact relay requires a verified sender** (behavior change — `EmailVerifiedRequiredMixin` moved to `accounts/mixins.py`, reused by contributions and contact); `igdb_import` over an existing game no longer wipes its Steam columns; employer quick-picks ordered dev→pub→porting→support; `company_create` rejects over-long names; DCO checked in CI on PRs; OSS scaffolding added (SECURITY.md, CODE_OF_CONDUCT.md, issue/PR templates, root CLAUDE.md); hosting story aligned across docs (Railway + R2, EU regions + DPAs).

- [x] **Public-release prep** (2026-08-21): `load_dev_fixtures` now **refuses to run outside `DEBUG`** (behavior change — `admin@example.com` / `admin` becomes a published credential pair the moment the repo is public, and DEBUG is the only signal separating a contributor's box from a real database); CI declares `permissions: contents: read`; `.gitignore` covers the agent-tooling directories (`.claude/launch.json` stays tracked); the prepare step's Steam-derived input is named `steam` (operator file: `steam.parquet`).

## Known follow-ups (tech debt, not blocking the POC)

- [x] **Bulk seed load** ✅ — the upsert is now a bulk loader (cached reference rows, `bulk_create`/`bulk_update`, in-Python slug allocation); the full ~392k catalog loads in ~2 min (was ~50 min per-row).
- [ ] **Company dedup / merge** (now more relevant at catalog scale — source names carry near-duplicate spellings even after trim/truncate cleaning): user-created companies (`source=manual`) are keyed only by exact name — near-duplicate spellings ("Virtuos" vs "Virtuos Games") can proliferate. Add a light admin merge tool (repoint `game_companies` + `contributions` to a canonical company, delete the dupe) once manual companies grow. The dormant `company_aliases` table (docs/04 §5) can back the merged names.
- [ ] **`display_name` has no btree index** — only the GIN trigram one (`user_display_name_trgm`), which the planner can't use for `ORDER BY`. The open recruiter search orders every result set by `display_name`, so a broad filter makes it sort the whole user table. Measured against 100k users / 600k credits on a 392k-game graph: adding `models.Index(fields=["display_name"])` to `User.Meta` halved a selective case (10.0ms → 4.9ms); worst legal case today is 118ms, so **not urgent**. It's an `accounts` migration — do it with the next one that touches the app rather than on its own.
- [x] **Redis for the rate limit** ✅ (2026-08-12) — prod's cache is Redis, so counters are shared across workers and survive; `REDIS_URL` is required and prod crashes without it, because a silent fallback is exactly the invisibility this fixed. A Redis outage un-meters rather than 500s (`RATELIMIT_FAIL_OPEN` plus django-redis's `IGNORE_EXCEPTIONS` — Django's built-in Redis backend catches nothing, so `RATELIMIT_FAIL_OPEN` would never run behind it) and is logged to `rollcall.cache`. Note the limits are now stricter by the old worker count without any number changing. Spec: `docs/superpowers/specs/2026-08-12-redis-rate-limit-design.md`.
- [ ] `search:suggest` (the nav typeahead) carries no rate limit for anyone, while every other search surface does. It runs three trigram searches per keystroke. Metering it changes behaviour on every page for every visitor, so it needs its own decision rather than a drive-by.
- [ ] A sustained Redis outage emits two ERROR log records with tracebacks per metered request (`add` and `incr` each hitting `DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS`), and Sentry's default logging integration (`event_level=ERROR`) turns each into a Sentry event — a busy outage could burn through a free-tier quota fast. That is the design working as intended (the outage must be loud), not a defect; a `before_send` sampler or a logging filter on `rollcall.cache` is the candidate fix if it becomes a problem.
- [ ] **Non-Steam facet coverage** (found 2026-08-12): the upstream IGDB export carries no ratings and no genre names, so IGDB-only games (~224k of ~392k) have neither — the people search's `min_rating` and genre filters silently exclude anyone whose matching credit is on a non-Steam game. The honest caveat now lives on the form's help text and in docs/01 §3.6; the real fix is adding `rating`/genre-name columns to the upstream export and wiring them through `games/seed/prepare.py`.
- [ ] `sitemap.xml` is a single sitemap — switch to a paginated sitemap index at ~400k games (see DEPLOY.md).
- [ ] `ty` runs without Django awareness (no plugin) — the codebase carries small typed accommodations (`AuthedHttpRequest`, `ClassVar` managers, `Any` bridges); revisit if `ty` ships Django support or if the tax grows.

---

## Deliberately NOT in the POC

Vouching UI (schema ships dormant) · company claim · manual game creation · internal messaging · payments · automated recruiter verification · moderation workflow beyond the report form · sub-disciplines · skills · Discord OAuth (first post-POC addition) · public API.

## Success metric (from docs/01-DESIGN.md §4)

1. Industry people, not individually solicited, create an account and declare ≥1 complete contribution.
2. A few real recruiters find the search, run searches, and send contact requests. (Reworded 2026-07-16 with docs/01-DESIGN.md §4: "apply, get approved" is a dormant flow since the search opened to all.)

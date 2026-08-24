# Rollcall — POC Roadmap

> Living tracking document. Check items off as they land; add notes/dates inline.
> Behavior source of truth: [docs/01-DESIGN.md](docs/01-DESIGN.md) · Build order from [docs/00-README.md](docs/00-README.md).
> When starting a phase, write a detailed implementation plan for it first (tasks, tests, code) — this file tracks *what*, the phase plans define *how*.

**Status legend:** `[x]` done · `[ ]` to do · ⚠️ blocked on something external

---

## Blocking prerequisites (external — before the seed phase)

These do not block Phases 0–1, but **must be resolved before coding the seed** (Phase 2):

- [x] IGDB/Twitch data agreement confirmed 2026-08-04.
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
- [x] Repo created on GitHub (`Micro-SAS/rollcall`; transferred to `Hushcrasher/rollcall` on 2026-08-21) and pushed

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

## Phase 2 — Seed pipeline ✅ (engine built; ⚠️ prepared-parquet wiring pending)

Goal: `python manage.py seed_games` — idempotent weekly refresh, DuckDB → Postgres.

Built test-first against a **documented assumed parquet schema** (`games/seed/schema.py`) — the contract a fork or the operator's prepared parquet must match. Pointing it at the operator's source later = adjust column names in `schema.py` + clear the prerequisites above.

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
- [x] Nav: ROLLCALL wordmark, `Add your credit` primary CTA (declare funnel for anonymous) (stacked `ROLL` / `CALL` since Phase 11)
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

## Phase 10 — Open Graph cards ✅ (spec 2026-08-21)

Goal: a Rollcall link previews richly wherever it is pasted; sharing a profile is one click.

- [x] `cards` app: pure Pillow renderer (Inter, OFL), `CardData` = the only fields a card may show
- [x] `/u/<slug>/card.png` (public profiles only), `/g/<slug>/card.png`, `/card.png` — cached 1 h, rate-limited, `?v=` token
- [x] `og:*` / `twitter:card` tags on every page; profile and game overrides; no tag ever carries an email
- [x] `profile_summary()` in `search/services.py` — one career aggregate for search cards and OG cards
- [x] Owner-only share row: copy link, LinkedIn / Bluesky / X, card preview
- [ ] v2: Noto fallback chain for non-Latin names (v1 renders the neutral card)

## Phase 11 — Search chrome ✅ (spec 2026-08-21)

Goal: a recognisable mark, filters that fit one screen, one word for reaching someone.

- [x] Stacked `ROLL` / `CALL` wordmark — system monospace in the nav, JetBrains Mono (OFL) on the OG cards
- [x] Filters in two named rows: *Games they worked on* · *About the person*; data caveat as one footnote — **superseded 2026-08-24: the two flat rows become one drawn card whose first section splits into two mutually exclusive sub-cards, and both row names are renamed** (*The games they've worked on* · *The person*), see Post-roadmap additions. The single data-caveat footnote is unchanged.
- [x] Banner trimmed to `Worked on a game? Add your credit` (still one translation unit)
- [x] `Message` buttons replace `Contact` links on profiles and search cards

## Phase 12 — Credit form v2 ✅ (spec 2026-08-21)

Goal: the common credit takes three fields and no guesswork.

- [x] Employer picker: the game's companies in a select, developer preselected; `No employer / freelance`; `Another company…` opens the search
- [x] Optional `country` on each credit (migration 0004) — shown after the dates, exported
- [x] `MM/YYYY` text inputs replace the locale-dependent native month picker (legacy `YYYY-MM` still accepted)
- [ ] Follow-up: credit country as a recruiter filter ("worked in …")

## Phase 13 — Game capsules ✅ (spec 2026-08-21)

Goal: a game looks like a game — on its page and on every credit line.

- [x] `Game.capsule_url`: the catalog's `cover_url`, else Steam's public header by `steam_appid` (derived, never fetched or stored)
- [x] Capsule on the game page; 92×43 thumbnails on profile credit lines and company game lists; `no-referrer`, hidden on load error
- [ ] Follow-up: capsules in search result cards (measure page weight first)

## Phase 14 — Public contact email ✅ (spec 2026-08-21)

Goal: a member can publish a contact address without exposing the account email that logs them in.

- [x] `public_email` field on `User` (migration `accounts/0008`): opt-in, blank by default, case-folded on every write path (settings form and admin alike, via a shared mixin) — separate from and independent of the account `email`, deliberately not unique
- [x] Renders as a `mailto:` link on the member's own public profile page only — to anonymous visitors and members alike — and nowhere else: not in cards, feeds, search-result cards, game or company pages, the sitemap, exports to third parties, or logs; a private profile still 404s for everyone but its owner
- [x] Owner sees a "Shown publicly" note next to the address, but only while their profile actually is public — a private profile's owner sees the address without the (otherwise false) note
- [x] The account email stays private and the relay stays the default contact channel; this is a second, narrower channel a member chooses to open
- [x] Policy texts amended for the new rule (docs/00 #1, `CLAUDE.md`'s first hard rule, docs/01-DESIGN.md §3.4/§3.6, docs/04-DATABASE-SCHEMA.md §1, `privacy.html`, `about.html`)
- [x] Negative tests: the address appears nowhere but the profile page (feed, search, game page, company page, sitemap, card PNG, profile meta tags, the contact relay's outbound mail) — plus the export sweep and account-deletion/no-email test zones re-run clean

## Phase 15 — Visual identity ✅ (2026-08-22)

Goal: stop looking like an unstyled framework demo, without turning it into a design project.

- [x] `static/css/theme.css` — the site's ONE aesthetic stylesheet, loaded after Pico and before `app.css`, scoped `:root[data-theme=light]` (0,2,0) so it outranks Pico's own light block without `!important`
- [x] Density: `--pico-font-size` fixed at 93.75% for every viewport (Pico's own scale reaches 131%), tighter rhythm, `--pico-border-radius: 0`, shadows off, monospace for data and Inter for prose
- [x] Two colours: text and headings `#3B0918` (17:1 on white — Pico colours headings from six variables of their own, so `--pico-color` alone was not enough), highlight `#647BCA` replacing Pico's blue in the seven variables Pico states literally, with the rest of the framework following through `var()`
- [x] Highlight contrast measured and accepted: 4.0:1 — clears AA for large text and UI components, just under the 4.5:1 normal-size text wants; `#5A70C0` (4.65:1) is the compliant shade of the same hue if it is ever wanted. An earlier single-accent `#DC4731` was rejected at 3.88:1 while it still carried body text
- [x] Inter vendored as subset woff2 (`static/fonts/`, OFL) — the same family `cards/` already renders the OG cards with
- [x] The declare funnel's game picks read as a list of records instead of eleven stacked primary buttons
- [x] Explored and **rejected** (recorded so they are not re-proposed): brutalism — thick rules, hard offset shadows, uppercase monospace buttons; ordered-dither texture borrowed from the operator's marketing site; the cream/red `#FFFCF2` + `#DC4731` pairing
- [ ] Follow-up: a dark palette — `theme.css` is scoped to `[data-theme=light]`, so a dark one is a second block rather than an edit to the first

## Post-roadmap additions

- [x] **Dev email backend** — prints a clean, copy-friendly body so console verification/reset links aren't corrupted by quoted-printable wrapping
- [x] **IGDB live fallback** (docs §3.1): `games/igdb.py` client (Twitch OAuth, cached token) + `import_igdb_game` (reuses the seed upsert, `source=igdb_live`) + login-gated search/import endpoints, folded inline into the credit-form game search as a "Not it? Search IGDB" option (local-first; IGDB only on deliberate click — rate-friendly). Hidden unless `IGDB_CLIENT_ID`/`SECRET` are set. Verified live end-to-end. **Superseded 2026-08-22**: the fallback is no longer a deliberate click. A search returning zero local rows queries IGDB automatically, on the credit form (`hx-trigger="load"`, no new JS) and in the anonymous funnel (server-rendered). Protection is a 24 h cache on the normalised query — misses cached too, since repeated misses are the traffic worth suppressing — plus `IGDB_RATELIMIT` (10/m per IP), which **skips the call instead of 403-ing the page**, and which a cache hit never spends. Search timeout 10s → 4s, since it now runs inside a page render. Spec: `docs/superpowers/specs/2026-08-22-igdb-auto-fallback-design.md`. **Amended 2026-08-22**: against the real 391k-game catalogue, "zero local rows" turned out to be effectively unreachable, so the auto-fallback's own trigger condition rarely fired and the anonymous funnel (which has no other IGDB path) still dead-ended on a missing game. Both surfaces now also carry an always-available manual escape hatch — `Not your game? Run a deeper search for "<query>"`, hidden unless IGDB is configured and not re-offered on a page that already ran one — that reaches IGDB even when local matches exist. The decision to drop "IGDB" from member-facing strings extends to all error and feedback messages: `Searching IGDB…` → `Running a deeper search…`; `No games found on IGDB.` → `The deeper search found no match.`; `That game is no longer listed on IGDB.` → `That game is no longer listed.`; and seven others. Three places deliberately still name the service — operator-facing Django admin field labels (`"IGDB user rating"`, etc.), the About page's data-provenance sentence, and the About page's `Game metadata © IGDB.com / Twitch` attribution (required by the provider's API terms).
- [x] **Live search everywhere**: nav bar typeahead dropdown (`/search/suggest/`) over games + people + companies; the full search page and nav both match companies now
- [x] **Open recruiter search** (2026-07-16): the search is open to everyone, anonymous included — the `RecruiterRequiredMixin` is deleted and the apply/approve flow goes dormant (still works, gates nothing). Multi-select engines/genres + person-level country filter (`User.country`, django-countries) via an htmx typeahead with chips (which replaced 249 country checkboxes — 34,908 bytes → 822 on every anonymous hit). Rich result cards: matching credits, "City · Country", career stats, labelled engine repartition % — **superseded 2026-08-24: results render as one comparison table, see Post-roadmap additions**. Pagination preserving filters. Mitigations are the IP rate limit + pagination + `profile_public`; the form's ≥1-filter rule is a UX guard, **not** an anti-enumeration boundary (docs/01-DESIGN.md §3.6). robots.txt now Allows the `/search/for-recruiters/` promise page while keeping the filter search disallowed. Spec: `docs/superpowers/specs/2026-07-16-open-recruiter-search-design.md`.
- [x] **Profile / Account split** (2026-08-04): the eight profile fields + GitHub URL move from `/settings/` to `/profile/edit/`; `/settings/` becomes `/account/` and keeps only email verification, JSON export and account deletion. A slugless `/profile/` resolves `LOGIN_REDIRECT_URL`, which now lands members on their own profile (a plain string setting can't pass a slug to `reverse()`). The profile page gains **View as member** (`?preview=member`, owner-only — for anyone else the param is inert; owner controls hidden and Contact/Report rendered as inert `<span>`s, since contacting yourself is refused by the relay) and a neutral **private-profile notice**: `profile_public=False` hides a member everywhere while `_visible_users` keeps showing them their own page, a silent state nothing else surfaced. The notice states the fact with a quiet link and does not push to reverse the setting — the flag is a safety valve. No migration. Verified in the browser, avatar upload included (the form's `enctype` is load-bearing and no test can catch it). Spec: `docs/superpowers/specs/2026-08-04-profile-account-split-design.md`.
- [x] **Constrained employer field**: picking a game loads its studios as quick-picks (`/games/<pk>/employers/`), with a "Worked for another company?" live search and a "Not there? Create '<name>'" path (`/companies/create/`, `source=manual`) for outsourcing studios missing from IGDB — **superseded 2026-08-21: the quick-picks and the "Worked for another company?" button are one `<select>` (developer preselected, then `No employer / freelance`, then `Another company…` revealing the same search); the endpoint's `?selected=` grew a `none` sentinel so a credit saved without an employer is never re-stamped with the developer**, see Phase 12 above. The create-company path is unchanged.
- [x] **The home page becomes the people search** (2026-08-11): `/` served a menu of four links that were all reachable from the nav bar anyway; it now serves the open people search directly, under the same URL name `home` (a view move, not a redirect, so `{% url 'home' %}` keeps resolving). The "For recruiters" promise page and the old landing are deleted outright — 404, no redirect, since nothing indexed points at either and the site is not deployed. Anonymous visitors get one pitch line plus a signup link above the form; members get the tool alone — **superseded 2026-08-20: the pitch line now reads "Worked on a game? Add your credit — no account needed to start." and links to the declare funnel at `/declare/`, not to signup directly**, see Phase 8 above. Two consequences carried the real work: the combinatorial filter-URL space moved to the root, where a path prefix cannot close it (`Disallow: /` would delist the site), so it is closed by query string with `Disallow: /*?` — honoured by Google and Bing, ignored by `urllib.robotparser`, with a `rel=canonical` as the second layer; and the IP rate limit had to stop applying to the bare page, or one office behind a single NAT would turn the front door into a 403 (quota is now spent only by requests carrying a query string). The nav box, now the only route to game/company lookup, says so: "Search games, companies and people". The recruiter application flow stays routed but unlinked. No migration. Spec: `docs/superpowers/specs/2026-08-11-home-is-people-search-design.md`.
- [x] **Deferred registration funnel** (2026-08-11): the home page asks "which game did you work on?" before it asks for anything else; the visitor fills a complete credit and creates the account at the end. The load-bearing discovery is that `SignupView` already auto-logs-in, so the account exists before the verification mail is opened — the credit becomes a row at signup with a new `Contribution.Status.PENDING` and is published by `verify_email`, which means verifying from a phone two days later works. Steps 1–3 hold raw form strings in the session (the session serializer is JSON, so `date` objects can't go there) and re-validate through `ContributionForm` before saving. The anonymous root leads with the question, so crawlers now index the home page under it — accepted knowingly — **superseded 2026-08-20: the question moved off the home page to its own `/declare/` URL; the home page now indexes under the recruiter-facing search question instead**, see Phase 8 above. `igdb_search`, `igdb_import` and `company_create` stay `@login_required`: a game missing from the catalogue converts into a signup rather than opening a write endpoint to anonymous traffic. One migration. Spec: `docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md`.
- [ ] **Referral loop** (deferred 2026-08-11, no spec yet): let a member name colleagues they worked with so Rollcall can invite them. Build the version where the invitation link lands the invited person on a *pre-filled* credit form — the data is shown only to the person it describes. Do **not** build the variant that publishes a "pending credits" list on game and company pages: a game page is public, so hiding it from search and the sitemap does not contain it, and it contradicts the rule that nobody writes another person's credit. Prerequisites: GDPR Article 14 handling and counsel review, a per-sender send limit like the contact relay's, a claim channel (pending entries without an email have none, so they shouldn't exist), and person-record dedup. Reasoning recorded in `docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md` §Deferred.

- [x] **Project review fixes** (2026-08-12, from `docs/reviews/2026-08-12-project-review.md`): fresh-clone Docker build repaired (collectstatic placeholder `REDIS_URL` + a CI `docker build` job + `.dockerignore` keeping `.env`/parquets out of image layers); dev settings tolerate a verbatim `cp .env.example .env`; **emails are case-folded** at signup/login/manager with a `Lower(email)` unique constraint (migration `accounts/0006`); **the contact relay requires a verified sender** (behavior change — `EmailVerifiedRequiredMixin` moved to `accounts/mixins.py`, reused by contributions and contact); `igdb_import` over an existing game no longer wipes its Steam columns; employer quick-picks ordered dev→pub→porting→support; `company_create` rejects over-long names; DCO checked in CI on PRs; OSS scaffolding added (SECURITY.md, CODE_OF_CONDUCT.md, issue/PR templates, root CLAUDE.md); hosting story aligned across docs (Railway + R2, EU regions + DPAs).

- [x] **Public-release prep** (2026-08-21): `load_dev_fixtures` **and** `seed_demo_people` now **refuse to run outside `DEBUG`** (behavior change — `admin@example.com` / `admin` and `demoN@example.com` / `demopass` become published credential pairs the moment the repo is public, and DEBUG is the only signal separating a contributor's box from a live database; both guards run before any row is written). Both documented onboarding paths keep working: `compose.yml` and `manage.py` both default to `config.settings.dev`, where `DEBUG=True`. CI declares `permissions: contents: read`; `.gitignore` covers the agent-tooling directories (`.claude/launch.json` stays tracked); the prepare step's Steam-derived input is named `steam` (operator file: `steam.parquet`); the About page and README carry the IGDB/Twitch attribution their API terms require.

- [x] **Dismissable autocompletes** (2026-08-22): every dropdown closes on outside press, on `Escape` and when focus moves to another control, and reopens on focus or the next swap — one shared `static/js/autocomplete.js`, document-level delegation, no template hook. `pointerdown` rather than `click` is load-bearing, though not for the reason folklore gives (hit-testing resolves the press target before any handler runs, so no dismisser can redirect an in-flight press): closing at press time is what native menus do, a touch scroll started outside the panel fires `pointerdown` but never `click` so scrolling dismisses on mobile, and a text-selection drag released outside the owner fires `click` outside it — which a `click` dismisser would misread and close the panel of the field being selected in. Panels are hidden, never emptied. The behaviour has no pytest coverage (no JS runner) — the spec carries a six-point browser checklist instead. Spec: `docs/superpowers/specs/2026-08-22-autocomplete-dismiss-design.md`.

- [x] **Profile-only Message button + layout polish** (2026-08-24): search result cards lose their `Message` button — the profile is the single contact entry point and now shows the button to every viewer but the owner, anonymous included (the relay's login + verified-email gates are unchanged). Alignment fixes, measured in the browser: the typeahead chips list renders truly empty so `.chips:empty` finally hides it (the dead list's margin pushed the Engines/Genres/Countries inputs 5px under their row neighbours), the open-to-work checkbox sits on its row's input line, and the nav's search field / CTA / links share one 37px box. The footer anchors to the viewport bottom on short pages via a flex-column `body` (`min-height: 100dvh`), never `position: fixed`. Spec: `docs/superpowers/specs/2026-08-24-profile-message-and-layout-polish-design.md`.
- [x] **Filter bento + a specific-games facet** (2026-08-24): the home page's filter block becomes one drawn card with a real type hierarchy (`theme.css` gave `label`, `legend` and `th` one `.8rem` mono bold, so the section names grouped nothing — legends now sit at `1.05rem`). Inside it, the three game criteria and a **new `games` facet** are drawn as two mutually exclusive cards with `OR` between them: naming games outright and describing them by genre/rating/engine answer the same question two ways, and combining them can only narrow a list of named games into nonsense. `clean()` refuses both at once; the page disables the empty side (disabled controls are not submitted, so that IS the browser-side mechanism), and the person section stays available in both modes. Row 1 reorders to genre · rating · engine, six of the seven existing labels are renamed out of database vocabulary ("Engines" → "Game engine", "Discipline" → "Their role"; only *Open to work only*, which was never database vocabulary, stays), and the field cells pack left — the old `minmax(13rem, 1fr)` stretched four controls across the full 72rem column. Two traps carried the real work: `TypeaheadSelectMultiple._chips()` builds its label map by iterating `self.choices`, which for `Game` would materialise ~391k rows **on every render of the home page** (a subclass looks up only the selected ids), and `?games=abc` would reach `pk__in` as a string — a 500 on a public page from a hand-typed URL. The games typeahead gets its own `filters/games/` endpoint rather than reusing the credit form's, which offers an IGDB import that cannot produce a match. **The narrow-viewport pass is deliberately deferred** — this ships only the stacking that keeps a phone usable; **done 2026-08-24, see the entry below**. Spec: `docs/superpowers/specs/2026-08-24-filter-bento-and-game-facet-design.md`.

- [x] **Mobile pass on the filter block and the nav** (2026-08-24, closing the deferral above): measured at 375px, every person-section field was 203px wide with **144px — 38% of the row — empty beside it**, because the desktop rules cap a cell at `13.5rem` and pack them left; the criteria card was worse at two 141px columns, wrapping `Minimum player rating (%)` onto two lines and clipping both placeholders mid-word. One full-width column below 768px fixes both, at the cost of one extra row: the block goes 942px → 1003px, legibility traded for height deliberately (a `<details>` disclosure that would have bought the height back was considered and declined). The nav, logged in, wrapped to **four rows and 167px** with `Log out` orphaned alone — its item group needs 389px in a 375px row, so no amount of free wrapping could seat it; the CTA now takes a full-width row of its own and the three secondary links share the next, giving three rows and 124px. The group's `<ul>` has to claim that row itself, since `nav` is a wrapping flex container and the `<ul>` otherwise sizes to its content — which is why the anonymous CTA came out 218px wide while the logged-in one looked full. A 2×2 grid was tried first and rejected: centred in their cells the items read as scattered. Desktop verified unchanged. **Still open:** at exactly 768px the criteria card shows two columns rather than three (2×202px is more readable there than 3×128px would be, so this is a judgement, not a defect), and the nav's last `<ul>` overhangs the viewport by ~7px — Pico's own negative margin for aligning nav links, pre-existing and visible only in a narrow window around that width.

- [x] **Engine families** (2026-08-24): a recruiter looking for Unity people had to tick thirteen boxes. The catalogue spells that one engine as `Unity`, `Unity3D`, `Unity 6`, `Unity 5`, `Unity 4`, `Unity 3` and `Unity 2017`–`2023` — **19,837 game-engine links, 36% of the catalogue's**, split across thirteen rows that each look like a separate engine; picking `Unity` alone silently missed `Unity3D`'s 1,003 games. It is not only versions: `renpy` and `Ren'Py Visual Novel Engine` are `Ren'Py` under other spellings, `Godot Engine` is `Godot`. A platform-owned `EngineFamily` table plus a nullable `Engine.family` groups **20 families over 89 engine names, ~76% of all game-engine links**; the mapping lives in `games/engine_families.py` and `link_engine_families` applies it (idempotent, run after every seed, and it *prints* mapped names that match nothing — which is how a typo surfaces). **Curated by hand on purpose:** measured against the seeded catalogue, a same-prefix rule files **RenderWare** (EA's, 120 games) under Ren'Py and **Crystal Engine**, **Crystal Tools** and **Cryptic Engine** under CryEngine. The typeahead is now one box over two fields — the family head first, its matching versions indented beneath (`?engine_families=` vs `?engines=`), OR'd together within the facet — which meant `addChip` had to dedupe by field name as well as value, since an engine pk and a family pk can be the same number. `EngineFamily`/`Engine.family` are platform-owned and the seed never touches them: `_ensure_refs` only ever creates a row, never updates one. Two specificity traps were measured rather than guessed while styling the indent — theme.css matches these options as `[type=button]` at (0,3,0), which beat two earlier attempts. One migration. Spec: `docs/superpowers/specs/2026-08-24-engine-families-design.md`.
- [x] **Engine picks become checkboxes** (2026-08-24, amending the entry above): a plain row of text gave no way to tell whether a click was taking the family or one version — the distinction the feature exists to draw. Options are checkboxes now; picking a family **ticks and locks** the versions it covers (so a reader sees what it reaches) and drops any version chips it supersedes, since both together post two filters meaning what the family means alone. The member whose name IS the family name is no longer listed — `Unity` under `Unity` reads as a version of itself — which makes that unversioned row (the catalogue's largest, 15,968 links) reachable only through its family, deliberately. The panel now stays open after a tick, a departure from the other three typeaheads that follows from the control rather than from taste. One defect found only in the browser: `syncExclusion` assigns `disabled` to every `input, select, button` in a filter group, which undid the family lock a millisecond after it was set; the dropdown panel is now exempt. No JavaScript runs in this project's tests, so nothing could have caught it.

- [x] **Search results as a table** (2026-08-24): a recruiter's job on this page is to **compare people**, and the results were a stack of cards — a shape that reads one person at a time and turns comparing two of them into a scroll and a memory exercise. Each card also spent vertical room on prose (`1 credit · 1 game · 2020–2021`) that is really four values. Seven columns now: name (with the `Open to work` badge beside it), based in, experience, credits, games, in the industry, engines on credited games. **The engine column merges by family** — `Unity 67% · Unity 6 33%` said nothing true about anybody, being one engine under two of its names, and reads `Unity 100%`; the SQL `.distinct()` dedupes `(user, game, engine)`, which is not enough once several engines collapse into one family, so the family key is deduped again in Python or a game tagged with two Unity spellings counts twice toward Unity. The header `Engines on credited games` is **load-bearing**: a bare percentage beside a person reads as a score *of them* (non-negotiable #7), and naming what the number measures is the same guard the card carried inline. No column rules, faint row rules only, inside an `overflow-x` wrapper so seven columns never push the page sideways. **Below 768px the table stops being a table** — `thead` hidden, every cell a block reinstating its own header from `data-label` via `::before`; horizontal scrolling was rejected because reading one person would mean dragging, on the surface most likely to be opened from a phone. `data-label` is therefore not decoration and a test asserts every cell carries one. One property is deliberately gone: the `{% blocktranslate count %}` plural on `1 credit`/`2 credits` — a count column is a bare number under a header and has no singular. Spec: `docs/superpowers/specs/2026-08-24-results-table-design.md`.
- [x] **Profile credits as a table, and the badge beside the name** (2026-08-24): the profile's credit list becomes a register — cover · game · role · company · dates — sharing a `.record-table` look with the search results — the two are the same object seen twice, so the styling was folded into one class rather than left to drift (no column rules, faint row rules only). **Column names are carried for screen readers and hidden from sight** (`.visually-hidden`): a credit line reads fine unlabelled, but a table with no headers at all announces as an unlabelled grid. The `Declared` badge is **removed** — every credit on that page is declared, so it marked nothing and only competed with the row it sat in. `Open to work` moves inside the `<h1>`, beside the name it qualifies, instead of sitting on a line of its own where it read as a heading. Owner-only Edit/Delete get a sixth column. On a phone the cells stack without reinstating headers, unlike the search results: these columns read fine in order, which is what the old card did. One test updated — the country still rides with the dates, but the cell is tighter than the old inline sentence.

## Known follow-ups (tech debt, not blocking the POC)

- [x] **Bulk seed load** ✅ — the upsert is now a bulk loader (cached reference rows, `bulk_create`/`bulk_update`, in-Python slug allocation); the full ~392k catalog loads in ~2 min (was ~50 min per-row).
- [ ] **Company dedup / merge** (now more relevant at catalog scale — source names carry near-duplicate spellings even after trim/truncate cleaning): user-created companies (`source=manual`) are keyed only by exact name — near-duplicate spellings ("Virtuos" vs "Virtuos Games") can proliferate. Add a light admin merge tool (repoint `game_companies` + `contributions` to a canonical company, delete the dupe) once manual companies grow. The dormant `company_aliases` table (docs/04 §5) can back the merged names.
- [ ] **`display_name` has no btree index** — only the GIN trigram one (`user_display_name_trgm`), which the planner can't use for `ORDER BY`. The open recruiter search orders every result set by `display_name`, so a broad filter makes it sort the whole user table. Measured against 100k users / 600k credits on a 392k-game graph: adding `models.Index(fields=["display_name"])` to `User.Meta` halved a selective case (10.0ms → 4.9ms); worst legal case today is 118ms, so **not urgent**. It's an `accounts` migration — do it with the next one that touches the app rather than on its own.
- [x] **Redis for the rate limit** ✅ (2026-08-12) — prod's cache is Redis, so counters are shared across workers and survive; `REDIS_URL` is required and prod crashes without it, because a silent fallback is exactly the invisibility this fixed. A Redis outage un-meters rather than 500s (`RATELIMIT_FAIL_OPEN` plus django-redis's `IGNORE_EXCEPTIONS` — Django's built-in Redis backend catches nothing, so `RATELIMIT_FAIL_OPEN` would never run behind it) and is logged to `rollcall.cache`. Note the limits are now stricter by the old worker count without any number changing. Spec: `docs/superpowers/specs/2026-08-12-redis-rate-limit-design.md`.
- [ ] `search:suggest` (the nav typeahead) carries no rate limit for anyone, while every other search surface does. It runs three trigram searches per keystroke. Metering it changes behaviour on every page for every visitor, so it needs its own decision rather than a drive-by.
- [ ] A sustained Redis outage emits two ERROR log records with tracebacks per metered request (`add` and `incr` each hitting `DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS`), and Sentry's default logging integration (`event_level=ERROR`) turns each into a Sentry event — a busy outage could burn through a free-tier quota fast. That is the design working as intended (the outage must be loud), not a defect; a `before_send` sampler or a logging filter on `rollcall.cache` is the candidate fix if it becomes a problem.
- [ ] **Non-Steam facet coverage** (found 2026-08-12): the upstream IGDB export carries no ratings and no genre names, so IGDB-only games (~224k of ~392k) have neither — the people search's `min_rating` and genre filters silently exclude anyone whose matching credit is on a non-Steam game. The honest caveat now lives in the search template's shared footnote (moved off the per-field help text 2026-08-21, spec `docs/superpowers/specs/2026-08-21-search-chrome-design.md`) and in docs/01 §3.6; the real fix is adding `rating`/genre-name columns to the upstream export and wiring them through `games/seed/prepare.py`.
- [ ] `sitemap.xml` is a single sitemap — switch to a paginated sitemap index at ~400k games (see DEPLOY.md).
- [ ] `ty` runs without Django awareness (no plugin) — the codebase carries small typed accommodations (`AuthedHttpRequest`, `ClassVar` managers, `Any` bridges); revisit if `ty` ships Django support or if the tax grows.
- [ ] **A narrow slug race in the anonymous IGDB import** (found 2026-08-22, review of `docs/superpowers/specs/2026-08-22-igdb-auto-fallback-design.md`): `games/seed/upsert.py`'s `_BulkLoader.preload()` reads the DB's slug set once per call, before its own `@transaction.atomic` `bulk_create`. Two concurrent `DeclareGameView` imports of *different* IGDB titles whose slugified titles collide can each allocate the same slug and race on `Game.slug`'s unique index instead of `Game.igdb_id`'s. `_import_picked_igdb_game`'s `except IntegrityError` recovery (`contributions/views.py`) re-reads the loser by its own `igdb_id` — which repairs a same-game double-click, the case it was written for, but here finds nothing, since the loser's row was never committed. The visitor sees `That game is no longer listed.` for a game that does in fact exist — a clean 200, not a 500, but the wrong message. Candidate fix: re-read by title/`igdb_id` together, or serialize slug allocation with `SELECT ... FOR UPDATE`.
- [x] **A structural guard against a test making a network call** ✅ (2026-08-22) — the root `conftest.py` carries an autouse `_no_outbound_network` fixture: `socket.socket.connect` raises on any non-loopback address and `urllib.request.urlopen` is refused outright. It exists because one test on the `feat/igdb-auto-fallback` branch stubbed `IGDBClient.get_game` but not `search_games`, and the untouched path reached `get_context_data` → `_offer_igdb_matches` → `cached_search` → a live `POST https://id.twitch.tv/oauth2/token`, which *passed* — caught by review, not by the suite. The failure is a `RuntimeError` on purpose: `games/igdb.py` and `accounts/github.py` both fold `URLError` into their own exception type, so a network-shaped error would be swallowed into the "third party is down" branch instead of failing the test. Loopback stays open for Postgres.
- [ ] **`REMOTE_ADDR` behind the deploy's edge proxy is unverified** (found 2026-08-22, review of `docs/superpowers/specs/2026-08-22-igdb-auto-fallback-design.md`): every IP limit keys on `REMOTE_ADDR`, and nothing in the app reads `X-Forwarded-For` (`SECURE_PROXY_SSL_HEADER` covers the scheme only). If Railway's edge presents its own address, the whole site shares one counter — `SEARCH_RATELIMIT` 403s strangers for each other, and `IGDB_RATELIMIT`'s 10/m effectively disables the fallback and the bound on the funnel's anonymous import. The direction is *stricter*, not spoofable, which is why it is a follow-up and not a blocker; the check and the (careful) fix are written up as DEPLOY.md §4d. Deliberately not fixed in code: trusting a forwarded header without knowing the proxy topology turns a shared counter into a spoofable one, and that is the operator's call.

---

## Deliberately NOT in the POC

Vouching UI (schema ships dormant) · company claim · manual game creation · internal messaging · payments · automated recruiter verification · moderation workflow beyond the report form · sub-disciplines · skills · Discord OAuth (first post-POC addition) · public API.

## Success metric (from docs/01-DESIGN.md §4)

1. Industry people, not individually solicited, create an account and declare ≥1 complete contribution.
2. A few real recruiters find the search, run searches, and send contact requests. (Reworded 2026-07-16 with docs/01-DESIGN.md §4: "apply, get approved" is a dormant flow since the search opened to all.)

# Rollcall project review — 2026-08-12

> Scope: full repository at commit `6876c3e`, reviewed against the docs pack
> (docs/00–04), ROADMAP.md, CONTRIBUTING.md, README.md, DEPLOY.md and the six
> specs in docs/superpowers/specs/. Method: docs first (intent), then code
> against intent, then a contributor simulation performed for real (clean-clone
> checkout, Docker build, native install, full test run). Everything below was
> verified by reading or executing the cited files; findings that could not be
> confirmed are in §7, not here.

## 1. Verdict

**Is it well thought out? Yes — unusually so.** The design decisions are
written down with their reasoning, the code implements them with rare
fidelity, and the comments explain *why* at exactly the places a reviewer
would ask. Invariants that matter (email never rendered, private profiles
invisible, single-credit filter semantics, seed write-surface) are held
structurally and pinned by tests that assert the actual invariant — 424 tests,
5 seconds, deterministic, no network. The one crack in the thinking is not in
the code but in the doc set: the authoritative documents disagree with each
other about hosting, about where the seed dedup lives, and — seriously —
about non-negotiable #6, which the deferred-registration funnel relaxes in
docs/01 while docs/00 (the file that "wins if in doubt") still states the
unrelaxed rule.

**Is it ready for outside contributors? No — not this week.** The
recommended onboarding path (`docker compose up`) fails at build on a fresh
clone (verified), the second step of the native path (`cp .env.example .env`)
500s every page unless the contributor guesses the fix (verified), the DCO
that CONTRIBUTING calls mandatory is enforced nowhere and only 32 of 99
commits in main comply with it, and the standard OSS floor (code of conduct,
security policy, issue/PR templates, a root CLAUDE.md for the AI-assisted
contributors this project will obviously attract) is absent. All of it is
cheap to fix. The bones are excellent; the front door is broken.

## 2. Top 5

1. **Unbreak the fresh-clone Docker build** ([Dockerfile:24](../../Dockerfile)
   runs `collectstatic` under prod settings, which since today's Redis commit
   crash without `REDIS_URL` — see S2-1). Two-line fix, plus a CI job that
   builds the image so this class of breakage can never land silently again.
2. **Amend docs/00 non-negotiable #6** to record the funnel's scoped
   relaxation (one sentence pointing at docs/01 §3.3). Right now the highest-
   authority doc and the code disagree, and a contributor obeying docs/00 will
   "fix" deliberate behavior (S1-1).
3. **Defuse the `.env.example` secret-key trap** (S2-2): make
   [dev.py:8](../../config/settings/dev.py) fall back on an *empty*
   `DJANGO_SECRET_KEY`, or ship the example with a dev default. One line.
4. **Decide the non-Steam facet story before launch** (S2-3): 57% of the full
   catalog has no rating and no genre data, so the `min_rating` and genre
   filters silently exclude every non-Steam credit while docs/01 promises IGDB
   ratings cover them. Either wire ratings/genres into the upstream export, or
   update docs/01 + the form's help text to tell the truth.
5. **Lay the contributor floor**: a DCO check (GitHub app or action), issue/PR
   templates that encode the checklist (typed, i18n, tests, sign-off),
   SECURITY.md, a code of conduct, and a root CLAUDE.md (§6). Also normalize
   email case at signup (S3-1) *before* real users exist — it is a one-line
   `clean_email` today and an account-merge project after launch.

Cheapest high-value: items 2 and 3 are one-liners; item 1 is two lines plus a
CI job.

## 3. Findings

### S1

### [S1] contributions/views.py:221 — the declare funnel violates non-negotiable #6 as written in docs/00, which was never amended
```
Evidence:    docs/00-README.md:19 — "6. Email verification required before
             creating a contribution." (header: "if in doubt, these win").
             contributions/views.py:228-239 (_save_credit) writes a
             Contribution row with status=PENDING for an unverified account;
             views.py:221 reaches it. docs/01-DESIGN.md:60 and the 2026-08-11
             funnel spec document this as a deliberate "scoped relaxation";
             docs/00 was not updated.
Why wrong:   Not the behavior — the publication invariant genuinely holds
             (nothing outside status=active renders anywhere; verified in
             search/services.py:177, accounts/views.py:160, games/views.py:30,51,
             config/sitemaps.py — and pinned by contributions/tests/
             test_pending_status.py). What is broken is the rule system: the
             document that declares itself supreme states a rule the code
             knowingly breaks, and the amendment lives two files away.
Consequence: A contributor (or their coding agent) reads docs/00 as
             instructed, concludes DeclareAccountView is a bug, and either
             files it or "fixes" it — destroying a shipped feature. Severity
             is per this review's own rubric (any docs/00 violation is
             critical); as user-facing risk it would be S3.
Fix:         One sentence appended to docs/00 #6: "(scoped relaxation: the
             declare funnel may write a `pending` row pre-verification;
             nothing unverified is ever published — see 01 §3.3)."
Confidence:  high
```

### S2

### [S2] Dockerfile:24 — a fresh clone cannot build the image; `docker compose up` (the README's recommended path) fails
```
Evidence:    Dockerfile:18 sets DJANGO_SETTINGS_MODULE=config.settings.prod;
             Dockerfile:24 runs collectstatic; config/settings/prod.py:15 is
             `REDIS_URL = env("REDIS_URL")` with no default. Executed for
             real: a `git archive HEAD` clean checkout fails at build with
             "django.core.exceptions.ImproperlyConfigured: Set the REDIS_URL
             environment variable" (build log, stage 7/7). Introduced by
             36a3cbb (2026-08-12). CI (.github/workflows/ci.yml) never builds
             the image, so nothing caught it.
Why wrong:   collectstatic needs settings import to succeed; prod settings now
             crash at import without REDIS_URL; the build has no .env and no
             REDIS_URL. The maintainers' local builds may still pass via
             Docker layer cache or a copied .env — see the .dockerignore
             finding (S3-5) — which is why it went unnoticed.
Consequence: Every new contributor following README.md:33-37 gets a build
             error naming a Redis they were never told about. The documented
             Railway deploy builds the same Dockerfile and fails the same way
             unless Railway injects service variables at build time (§7).
Fix:         Give the collectstatic RUN a placeholder
             (`REDIS_URL=redis://collectstatic-placeholder`) alongside the
             existing fake SECRET_KEY — collectstatic never touches the cache
             — or introduce a build settings module. Add `docker build .` to
             CI.
Confidence:  high (reproduced)
```

### [S2] .env.example:4 + config/settings/dev.py:8 — following the README's native path verbatim 500s every page
```
Evidence:    README.md:42 says `cp .env.example .env  # fill in
             DJANGO_SECRET_KEY at least`. .env.example ships
             `DJANGO_SECRET_KEY=` (present, empty). django-environ returns ""
             for a present-but-empty variable, so dev.py:8's
             `env("DJANGO_SECRET_KEY", default="dev-only-insecure-key")`
             never falls back. Executed for real on the clean clone: migrate
             and load_dev_fixtures succeed, then every page is 500
             "The SECRET_KEY setting must not be empty." Skipping the `cp`
             entirely works fine.
Why wrong:   The one file copied to make setup easier is the only thing that
             can break it, and the failure appears three commands later with
             an error that names none of the cause.
Consequence: A contributor who treats "fill in … at least" as optional (dev
             settings advertise a fallback, so it reads optional) gets a fully
             migrated, fixture-loaded app in which every URL 500s.
Fix:         dev.py: `SECRET_KEY = env("DJANGO_SECRET_KEY", default="") or
             "dev-only-insecure-key"` — or comment the line out in
             .env.example the way REDIS_URL's note explains itself.
Confidence:  high (reproduced)
```

### [S2] games/seed/prepare.py:80-81 — with the full catalog, the rating and genre facets exclude 57% of it; docs/01 §3.6 promises otherwise
```
Evidence:    prepare.py:80-81 hardcodes `NULL::DOUBLE AS igdb_rating` (both
             branches) and prepare.py:38 takes genres from the Steam-side file
             only (`COALESCE(hc.genres, …)`); the upstream
             data/igdb/igdb_games.parquet has no rating or genre-name columns
             (verified by DESCRIBE). Measured on data/rollcall_games.parquet:
             224,477 of 391,425 rows are IGDB-only, and 100% of them have
             len(genres)=0 and no rating of either kind; zero rows in the
             whole catalog carry an igdb_rating. The filter
             (search/services.py:189-192) is `steam_positive_pct >= X OR
             igdb_rating >= X`; docs/01-DESIGN.md:91 promises "IGDB ratings
             for non-Steam games".
Why wrong:   The recruiter search is the declared product promise
             (docs/02 §7 zone 2). Any `min_rating` value — including the
             gentlest, 1 — removes every person whose matching credit is on a
             non-Steam game (console, mobile, itch, cancelled). Genre filters
             do the same. Nothing in docs or the UI says so.
Consequence: A recruiter filters "RPG, rating ≥ 70" and silently loses every
             console-only developer in the database; the worker who declared
             that credit is unfindable through exactly the filters the pitch
             advertises.
Fix:         Short term, truth in docs/UI: note on the rating/genre fields
             that they currently cover Steam-linked games only, and amend
             docs/01 §3.6. Real fix: add rating/genre names to the upstream
             IGDB export and wire them through prepare.py (the schema and
             seed already accept them).
Confidence:  high on the data and mechanism (measured); the prepared parquet
             on this machine is presumed representative of production.
```

### [S2] games/igdb.py:157 — importing an already-seeded game wipes its Steam identity and rating until the next weekly seed
```
Evidence:    igdb_to_canonical (games/igdb.py:126-143) builds a CanonicalGame
             with steam_appid=None, steam_positive_pct=None,
             steam_review_count=None. import_igdb_game:157 feeds it to
             upsert_games, whose update path writes ALL of _SOURCE_FIELDS
             (games/seed/upsert.py:128-142, 166-170) — including the Nones —
             onto the existing row matched by igdb_id. Reproduced live:
             a game with steam_appid=200133, steam_positive_pct=69.00 came
             back `None / None / igdb_live` after one import.
Why wrong:   The upsert treats "the canonical has no Steam data" as "erase the
             Steam data", for a source (IGDB live) that by construction never
             carries Steam fields.
Consequence: Any logged-in member POSTs an igdb_id to /games/igdb/import/
             (games/views.py:116, login-only) — or legitimately clicks
             "Search IGDB" on a title whose local copy they didn't recognize —
             and the game drops out of every rating filter and loses its
             steam_appid link. Self-heals only when the weekly seed runs,
             which is not yet scheduled anywhere.
Fix:         In the upsert, drop the always-None fields from the
             bulk_update field list when source=igdb_live (or merge: only
             overwrite fields the canonical actually carries for that source).
Confidence:  high (reproduced)
```

### S3

### [S3] accounts/forms.py:16 — email uniqueness and login are case-sensitive; duplicate accounts verified
```
Evidence:    User.email is a plain unique EmailField (accounts/models.py:69);
             SignupForm saves via ModelForm (no normalization; UserManager's
             normalize_email is bypassed because form.save() doesn't call
             create_user). Reproduced live: `Case.Test@Example.com` and
             `case.test@example.com` both created; login
             (ModelBackend.get_by_natural_key) is exact-match.
Why wrong:   docs/04 §1 specifies "citext/varchar" for exactly this reason;
             the varchar half shipped without the case-insensitivity half.
Consequence: A user signs up on a phone (autocapitalized "John@…"), later
             types "john@…" — "no account found". Password reset uses
             __iexact (Django default) and will happily email BOTH duplicate
             accounts. Post-launch cleanup means merging accounts.
Fix:         Lowercase in SignupForm.clean_email + a lowercasing
             EmailAuthenticationForm.clean, plus a data migration and a
             CI-friendly functional unique index (Lower("email")).
Confidence:  high (reproduced)
```

### [S3] contact/views.py:27 — the relay is usable by unverified accounts, with an unverified Reply-To
```
Evidence:    ContactView has LoginRequiredMixin only (contact/views.py:27-39);
             no is_email_verified check. _send sets
             `reply_to=[sender.email]` (contact/views.py:79) — an address the
             sender never proved they own. Accounts are free and signup has no
             rate limit (acknowledged in search/views.py:166-169's comment).
Consequence: A spammer scripts signup (no verification click needed to log
             in), then sends 20 relay messages/day/account from Rollcall's
             domain, with Reply-To pointed at any third party's address —
             burning sender reputation and harassing via a header the victim
             never chose. The DB audit trail records a throwaway.
Why wrong:   The email-verified gate exists as "the first anti-spam line"
             (docs/01 §3.4) but covers only contributions; the one feature
             that sends outbound email on a user's behalf is outside it.
Fix:         Require is_email_verified in ContactView.dispatch (mirrors
             EmailVerifiedRequiredMixin). One condition + one test.
Confidence:  high on mechanism; whether unverified-contact was a deliberate
             product choice is for the maintainers to say — no doc claims it.
```

### [S3] templates/legal/privacy.html:13 — "We host in the EU." and four other files still tell the pre-Railway hosting story
```
Evidence:    privacy.html:13 ("We host in the EU"), README.md:27 ("deployed on
             an EU PaaS"), docs/02-ARCHITECTURE.md:67-70 (Scalingo/Clever
             Cloud, prefer Scaleway), docs/03-TECH-STACK.md:31-33 (same),
             docs/01-DESIGN.md:101 ("EU hosting … no extra-EU transfer
             paperwork"). Against: ROADMAP.md:17 and DEPLOY.md:3-4, which
             record the actual decision — Railway + Cloudflare R2, both US
             companies, "pick EU regions + sign DPAs".
Why wrong:   ROADMAP/DEPLOY are correct and honest (EU region of a US
             processor requires DPAs/SCCs — the "no transfer paperwork"
             rationale in docs/01 no longer holds). The other five files, one
             of them a user-facing legal page, assert the older, stronger
             claim.
Consequence: A privacy-conscious user (this product's core audience) reads
             "We host in the EU" and gets a stronger claim than the
             infrastructure straightforwardly delivers; a new contributor
             reads docs/02 §5 and provisions the wrong stack.
Fix:         One sweep: update docs/02 §5, docs/03 infra table, README stack
             line, docs/01 §3.7 to "EU region on US-owned providers, DPAs
             signed"; soften privacy.html to "hosted in the EU region of our
             providers" pending counsel (it is already flagged for review).
Confidence:  high
```

### [S3] CONTRIBUTING.md:5 — the mandatory DCO is enforced by nothing, and main itself doesn't comply
```
Evidence:    CONTRIBUTING.md:5-15: "Every commit must be signed off."
             .github/workflows/ci.yml checks ruff/format/ty/pytest only.
             Measured: 32 of 99 commits in main carry Signed-off-by.
Why wrong:   A provenance rule that only a human enforces will not survive
             external contributors — and enforcing it on outsiders while the
             maintainers' own history is 2/3 unsigned is untenable in review.
Consequence: External PRs land unsigned; the AGPL provenance protection the
             DCO exists to give is absent exactly where it matters (code you
             didn't write).
Fix:         Add the DCO check (GitHub App or amannn/action-dco-style step) as
             a required status; decide whether history needs a one-time
             retroactive sign-off statement (common practice: a DCO-adoption
             commit declaring all prior commits maintainer-owned).
Confidence:  high
```

### [S3] Dockerfile:16 — no .dockerignore: local image builds bake in `.env` and the private parquets
```
Evidence:    `COPY . .` (Dockerfile:16 context); no .dockerignore exists
             (checked). A maintainer's working tree contains `.env` (secrets)
             and the local parquets under `data/` (the private data the
             .gitignore carefully keeps out of git).
Why wrong:   .gitignore does not apply to docker build contexts. The privacy
             boundary docs/02 §6 draws ("parquet URL, credentials, and DB
             dumps are private") holds in git and breaks in any locally built
             image.
Consequence: One `docker build` on the maintainer's machine followed by a
             push to any registry would carry those files in an image layer.
             It also explains why the broken collectstatic step (S2-1) went
             unnoticed locally: a copied .env or cache can mask it.
Fix:         A .dockerignore mirroring .gitignore's data/, *.parquet, .env,
             .venv, media/, plus .git.
Confidence:  high on mechanism; no evidence an image has actually been pushed.
```

### S4

### [S4] docs/02-ARCHITECTURE.md:42 — three documents still say the Steam↔IGDB dedup lives in the seed command; it moved to the prepare step
```
Evidence:    docs/02 §3:42 ("performs the Steam↔IGDB deduplication/merge in
             SQL, then upserts"), ROADMAP.md:60 ("dedup/merge in SQL
             (games/seed/pipeline.py)"), seed_games.py:3-4 (same claim).
             Reality: pipeline.py:1-5 is "a straight projection — the merge
             already happened in prepare.py"; the merge lives in
             games/seed/prepare.py + the prepare_seed_parquet command, which
             only DEPLOY.md §5 documents.
Consequence: A forker doing the "cleanliness test" is sent to the wrong file;
             the real fork boundary (schema.py's 16-column contract) is
             documented only in schema.py's docstring and .env.example.
Fix:         Update the three references; add one line to CONTRIBUTING's
             cleanliness-test paragraph pointing at games/seed/schema.py.
Confidence:  high
```

### [S4] games/views.py:90 — employer quick-picks order contradicts the docstring
```
Evidence:    Docstring (views.py:85-86): "ordered developer → publisher →
             porting → support". Code: `.order_by("role")` sorts the enum
             *strings* alphabetically: developer, porting, publisher,
             supporting (games/models.py:270-274).
Consequence: Publishers sort after porting studios in the quick-pick list —
             cosmetic, but the comment asserts an order the code doesn't give.
Fix:         An explicit ordering list (Case/When or sort in Python), or fix
             the docstring.
Confidence:  high
```

### [S4] games/views.py:108 — company_create accepts a >300-char name and will 500
```
Evidence:    Company.name is max_length=300 (games/models.py:81);
             company_create passes request.POST["name"] to get_or_create with
             no form/length validation (views.py:105-110).
Consequence: A member pasting an over-long name gets a raw 500 (Postgres
             DataError) instead of a form error. Login-gated, low blast
             radius.
Fix:         Truncate or validate (`if len(name) > 300: return JsonResponse
             error`), matching the seed's own left(trim()) discipline.
Confidence:  high (mechanism from schema; not executed)
```

### [S4] Three tests exercise a path without asserting its invariant
```
Evidence:    accounts/tests/test_account_management.py:85
             (test_delete_page_shows_confirmation asserts only status 200);
             games/tests/test_employer.py:40 (test_company_create_requires_login
             asserts 302 but not that no Company was created);
             games/tests/test_igdb_endpoints.py:61 (same pattern for import).
Consequence: A regression that creates the row and then redirects — exactly
             the failure mode a login guard exists to prevent — passes both
             write-path tests.
Fix:         One state assertion each (`assert not Company.objects.exists()`,
             etc.).
Confidence:  high
```

### [S4] accounts/forms.py:16 — signup enumerates accounts; password reset was carefully written not to
```
Evidence:    SignupForm inherits the unique-email validation ("User with this
             Email address already exists"), while
             password_reset_done.html:8-9 uses the non-enumerating "If an
             account exists…" wording.
Consequence: Whether "this address has a Rollcall account" is a secret gets
             two different answers from two adjacent endpoints. For a product
             whose users may be hiding from harassers, the strict answer is
             the safer default — but this is the standard Django trade-off.
Fix:         Either accept it consciously (a line in docs/01 §3.7) or move
             signup to a "check your email" pattern. The former is fine.
Confidence:  high on behavior; product judgment is the maintainers'.
```

### [S4] config/settings/base.py:135 — tests write into the repo's media/ directory
```
Evidence:    MEDIA_ROOT = BASE_DIR / "media" applies in test settings; the
             avatar-deletion test uses default_storage, and a leftover
             media/avatars/avatars/me.png sits in the working tree now.
Consequence: Cross-run state in the repo (gitignored, but accretes files if
             the delete-path assertion ever weakens).
Fix:         Override MEDIA_ROOT to a tmp path in config/settings/test.py.
Confidence:  high
```

### [S4] docs/03-TECH-STACK.md:78 — the env-var block drifted from .env.example
```
Evidence:    docs/03 lists `EMAIL_API_KEY=` (Brevo); the real configuration is
             EMAIL_HOST_USER/EMAIL_HOST_PASSWORD SMTP (prod.py:81-88,
             .env.example). docs/03's dependency list also omits
             django-countries, django-redis, django-environ, pillow (it is
             marked "indicative", so this is only worth a sweep, not a rule).
Consequence: None behavioral; a reader configuring from docs/03 sets a
             variable nothing reads.
Fix:         Point docs/03's env section at .env.example instead of
             duplicating it (see redundancy map).
Confidence:  high
```

## 4. Redundancy map

| Concept | Copies | Verdict |
|---|---|---|
| **Hosting/infra story** | docs/02 §5, docs/03 infra table, README stack line, docs/01 §3.7, privacy.html vs ROADMAP prerequisites + DEPLOY | **Already drifted — the S3 finding.** Make ROADMAP/DEPLOY canonical; the others should point, not restate. |
| **Env-var reference** | docs/03 §env, .env.example | Drifted (EMAIL_API_KEY). Keep .env.example canonical; docs/03 links to it. |
| **Seed pipeline description** | docs/02 §3, ROADMAP Phase 2, seed_games.py docstring vs prepare.py reality | Drifted together (S4). Same cure: describe once in docs/02, cite from elsewhere. |
| **Non-negotiables** | docs/00 (ten), README (four) | README's subset is fine as marketing; docs/00 #6 is the one that must absorb the funnel amendment (S1). |
| **Success metric** | docs/01 §4, ROADMAP twice (line 133 area + end) | Consistent today; three copies of a metric that already got reworded once (2026-07-16) will drift. Two would do. |
| **Fallback-if-schedule-slips plan** | docs/01 §4, DEPLOY end | Consistent, duplicated; harmless. |
| **Single-pick autocomplete UI** | contribution_form.html:14-25 + 60-94, declare_details.html:42-79, _employer_field.html, backed by _game_options/_company_options/_employer_options partials | Three *ideas* exist (single-pick, chips multi-select, nav dropdown) and should stay distinct. The one real merge target is the **~20-line JS fork between contribution_form.html and declare_details.html** — the 7-line "Worked for another company?" handler is byte-identical in both. Move it to a `<script>` shipped with _employer_field.html. The four near-identical option-button partials each carry a distinct tail (IGDB trigger, auth hints, other-toggle); merging them into a flag-driven partial is a net loss — leave them. |
| **Chips widget** | TypeaheadSelectMultiple + typeahead_select.html + _filter_options.html ×3 fields | Already fully factored. Nothing to do. |
| **Rate-limit reasoning** | search/views.py:154-179 comment, specs, DEPLOY §4c | Deliberate, documented cross-references — load-bearing, keep. |
| **Date-order validation** | ContributionForm.clean + DB CheckConstraint | Belt-and-braces by design, keep. |

## 5. Open-source readiness (Pass 3)

### Clone to running app — as it actually went

Clean checkout (`git archive HEAD`), following README.md literally.

**Docker path (README's "recommended for a first run"):** `docker compose up`
→ the web image build reaches `RUN … collectstatic` and dies:
`ImproperlyConfigured: Set the REDIS_URL environment variable`. **Dead end at
minute ~2**, with an error about a service the README never mentions (S2-1).
Even with the build fixed, the compose command runs only `migrate` +
`runserver` — the Docker path never loads `load_dev_fixtures`, so the
Docker-first contributor lands on an empty database; the README mentions
fixtures only under the native path. (This confirms the suspected lead.)

**Native path:** `cp .env.example .env` → `uv sync` (0.4s warm; a few minutes
cold) → `docker compose up db` (instant) → `migrate` (4.5s) →
`load_dev_fixtures` (12s, prints credentials — nice) → `runserver` → **every
page 500s** ("SECRET_KEY must not be empty"), because the copied .env's empty
`DJANGO_SECRET_KEY=` overrides dev's fallback (S2-2). Fill the key → root
serves the funnel question + people search, filtered search 200, robots.txt
exactly as documented. **~6 minutes for someone who diagnoses the 500; a
plausible rage-quit for someone who doesn't.**

### Clone to first merged PR

Once running, the path to a change is genuinely good: apps map to domains,
every module docstring cites the doc section it implements
(`contributions/models.py` → docs/04 §7-9), and the specs explain the
surprising recent parts. A newcomer fixing, say, the employer quick-pick
ordering (S4) would find games/views.py in one grep and a test file next to
it. What's missing is the *map*: nothing in CONTRIBUTING says "app = domain,
services.py owns search logic, templates/ is shared, specs explain the last
six features". Five sentences would do. There are no labelled starter issues
(none in the repo; remote labels unverified — §7).

### Are the rules executable or documentary?

| Rule | Enforced by | Status |
|---|---|---|
| Fully typed Python | ruff `ANN` + `ty check` in CI | **Executable** ✅ |
| Lint/format | ruff in CI | **Executable** ✅ |
| Tests pass | pytest in CI (with real Postgres service) | **Executable** ✅ |
| Never expose an email | 6 per-surface regression tests assert the literal address is absent (accounts, contact, games, search ×2, github block) + `User.__str__ = display_name` making the safe thing the default | **Semi-executable** — new surfaces depend on review, but the design makes leaking hard |
| Seed write-surface | test_seed_upsert pins slug/contribution survival and never-delete | **Semi-executable** ✅ |
| No public negative signals | nothing | **Documentary** — currently held (verified sweep found zero violations), but only review protects it |
| Every string through i18n | nothing | **Documentary** — currently *perfect* (a full sweep found zero raw strings, including inline JS and emails), which proves the discipline but not its survival under contributors |
| DCO sign-off | nothing; 32/99 commits in main comply | **Documentary and failing** (S3) |
| docs/00 non-negotiables as a set | nothing | Documentary; and #6 already drifted (S1) |

The two documentary rules that will actually get broken by well-meaning
contributors are i18n and negative-signals. i18n can be cheaply
semi-enforced: a test that greps templates for visible-text patterns outside
`{% translate %}` would catch the common case.

### Project scaffolding — what's missing and what it costs

Present: LICENSE (AGPL, commit 1 ✅), CONTRIBUTING, CI, excellent docs.
Absent, in order of real cost:

1. **SECURITY.md** — a privacy-centric product with no disclosure channel
   invites public issue-tracker vulnerability reports about a database of
   real people. Highest-cost absence.
2. **DCO enforcement** (S3) — the one legal mechanism CONTRIBUTING relies on.
3. **PR template** — the quality bar (typed, i18n, tests, sign-off, docs
   updated) exists only as prose a submitter has already scrolled past.
4. **Code of conduct** — this project's own design doc cites harassment as a
   first-order risk in its industry; a community repo without a CoC is
   off-message and blocks the GitHub "community standards" checklist.
5. **Issue templates + starter labels** — cheap, and the difference between
   "bug: search broken" and an actionable report.
6. A stated **review/merge process and release cadence** — one paragraph in
   CONTRIBUTING ("maintainer review, squash merge, deploy from main, no
   release schedule during POC") would set expectations honestly.

### AI-assisted contributors

There is no root CLAUDE.md, and for this repo that is a real gap: the
maintainers' own workflow (`.claude/`, docs/superpowers/) shows agents wrote
much of this code, and outside contributors will arrive with agents too. A
root CLAUDE.md should carry, in rough priority: (1) read docs/00 then
docs/01, the ten non-negotiables verbatim — especially never-expose-email,
no-negative-signals, i18n-everything, seed-write-surface; (2) the toolchain
contract (`uv run pytest` / `ruff check` / `ruff format --check` / `ty
check`, Postgres via `docker compose up db`); (3) fully-typed rule and the
existing `ty` accommodation idioms; (4) the three non-negotiable test zones
and the TDD expectation; (5) commit style incl. `-s` sign-off; (6) "when you
change behavior, update docs/01 + ROADMAP in the same PR" — the discipline
the maintainers themselves follow.

**Specs vs plans:** the six files in docs/superpowers/specs/ are genuine
design records (~200 lines each, decisions + reasoning + testing contracts)
— a contributor **should read the spec** for any surface they touch, and
ROADMAP already links them. The six files in docs/superpowers/plans/ are
execution transcripts (~8,500 lines total) — internal exhaust worth keeping
for archaeology but not reading. **Nothing anywhere says this.** One
paragraph in CONTRIBUTING or a README in docs/superpowers/ should: "specs are
binding design records; plans are historical execution logs."

### The fork test

**Passes, verified at the code level.** The app runs fully on
`load_dev_fixtures` with no parquet (done in this review). The seed boundary
is real: `seed_games` reads any local/HTTP/S3 parquet matching the 16-column
contract in games/seed/schema.py; nothing else in the app imports duckdb or
touches parquet (checked); parquets and credentials are gitignored and absent
from history (checked). What a forker must do: produce a conforming parquet
(their own prepare step — Hushcrasher's prepare.py is cleanly separable and
theirs to discard) and set `PARQUET_SOURCE_URL`. What's missing is
discoverability: CONTRIBUTING names the cleanliness test without pointing at
schema.py, and docs/02 §3 sends the reader to the wrong file (S4). One
sentence fixes it.

### Cost of contribution

Remarkably low once past the front door: **424 tests in ~5.2s** (measured),
deterministic (seeded RNG, stubbed network, no sleeps; one mild Dec-31
time-dependence in the GitHub-service tests), requiring only Docker-Postgres
— no Redis, no API keys, no network. The whole quality gate (ruff + ty +
pytest) runs in well under a minute. The contributor tax is entirely
concentrated in S2-1 and S2-2.

## 6. What is genuinely good — do not break these

- **`User.__str__` returns `display_name`** (accounts/models.py:143). This
  single choice is why the email rule holds across admin autocompletes, form
  labels, and every `{{ user }}` — six surfaces at once. Guard it.
- **The test suite asserts invariants, not execution.** The same-credit rule,
  vouch anonymization vs cascade direction, the largest-remainder
  percentages, an N+1 bound via `assert_num_queries`, mutation-tested form
  guards, and literal-email-absence checks on six surfaces. All three
  docs/02 §7 zones are genuinely covered (26 / 53 / 9 tests).
- **Write-surface discipline is structural**: upsert.py writes an explicit
  field list, never deletes, and admin mirrors it with per-source read-only
  fields — the doc, the code and the back-office agree.
- **Comments state constraints, not narration** — the rate-limit group
  naming (renames would silently move counters), the fail-open reasoning
  chain in prod.py, the `isdecimal` vs `isdigit` note, the choices-callable
  i18n trap. This is the best-commented Django codebase this reviewer has
  seen at POC stage; it is the project's real onboarding asset.
- **The specs record reversals honestly** (the 249-checkbox amendment, the
  corrected Paginator rationale, the non-negotiable-#6 relaxation argued
  rather than glossed). Whatever process produced these, keep it.
- **i18n discipline is at 100%** with zero catalogs shipped — the cheap-now,
  painful-later bet was actually executed, including inline JS and emails.
- **The security posture is honest**: "UX guard, not a boundary" is enforced
  in docs, comments and tests alike; nobody oversold the ≥1-filter rule.

## 7. Open questions

1. **Does the Railway deploy actually build?** Railway exposes service
   variables at build time in most configurations, which would mask S2-1 in
   production deploys (while leaving every contributor and fork broken).
   Settle: one test deploy, or check Railway's build-args behavior for
   Dockerfile builds.
2. **Is the local `data/` representative of the production parquet?** The
   57%-no-facets measurement (S2-3) ran on the prepared parquet on this
   machine. If a newer upstream export carries ratings/genres for IGDB rows,
   the finding shrinks to a doc fix. Settle: DESCRIBE the parquet in the
   private R2 bucket.
3. **GitHub block "prefer stale" promise**: the spec says any refresh error
   should prefer serving stale data; `_record_status` flips the snapshot to
   ERROR while keeping old fields (accounts/github.py:310-319). Whether the
   template then renders the stale data or an error state was not verified.
   Settle: read `_github_block.html`'s branching for status="error" with
   `has_data=True`, or add the test the spec promised.
4. **Remote repo state**: labels, starter issues, branch protection, required
   checks — not inspectable from this checkout. The scaffolding findings in
   §5 assume none exist.
5. **Was unverified-account relay access a deliberate choice?** (S3-2). No
   doc records a decision either way; the fix is one line if it wasn't.

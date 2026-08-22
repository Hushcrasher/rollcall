# Design Document — Game Industry Credits Platform (POC)

> Status: validated product decisions, ready for implementation.
> Companion docs: `02-ARCHITECTURE.md`, `03-TECH-STACK.md`, `04-DATABASE-SCHEMA.md`.

## 1. Vision

A "LinkedIn for the video game industry" **without the social network part** (no feed, no posts). The platform is a credits and discovery database built around three entities: **people**, **games**, and **companies**.

It addresses two industry problems:

1. **Missing credits.** Many workers are not credited on games they genuinely worked on. Here, a person *declares* their contribution ("I worked on game X, as [job title], from [date] to [date]"), and later, peers who worked on the same game can confirm it (peer-vouching system — designed into the schema, **not built in the POC**).
2. **Industry layoffs.** Recruiters need a better way to find relevant profiles. The platform offers a recruiter search that filters *people* by *properties of the games they worked on* (engine, genre, ratings, discipline, dates) — something generalist platforms cannot do.

**Codebase is open source (AGPL v3). The database is private**, operated by Hushcrasher (the company legally behind the project).

## 2. Core principles (drive every decision below)

- **Truth comes from workers, validated by peers** — not from official credits. Declarations are visible by default; confirmation is a bonus, not a gate.
- **Being findable IS the service** (IMDb model). All public profiles are visible to everyone, including recruiters. No separate "searchable by recruiters" opt-in.
- **Never expose personal emails.** All contact goes through a relay.
- **No public shaming.** No negative votes, no public "disputed" labels, no public reliability scores. Disputes are handled privately via reports and moderation.
- **The app's Postgres database is autonomous.** External sources (Hushcrasher parquet, IGDB) feed it via batch; no runtime dependency on them.
- **Keep doors open in the schema, keep the POC small in UI.** Several columns/tables exist from day one with no UI ("dormant").

## 3. Entities and key modeling decisions

### 3.1 Games

- **Source of truth: Hushcrasher's existing parquet file** (all Steam + all IGDB games, refreshed weekly), loaded into the app's Postgres by an idempotent batch seed job. Live IGDB API is only a fallback for very recent games missing from the last refresh (can be handled manually during the POC).
- **Internal ID is the pivot.** `igdb_id` and `steam_appid` are nullable unique columns. Nullable keeps the door open for future manually-created games (out of POC scope: IGDB is the only source of games for now — no game creation form, no game moderation, no dedup problem).
- **Fields imported from the source are read-only** in the app and overwritten on every weekly refresh. Platform-owned data lives in separate columns/tables. → Zero conflict possible by construction.
- **Editions/remasters/DLC:** one record per canonical game, with a nullable `parent_game_id` self-reference (mirrors IGDB's `parent_game`/`version_parent` model). Schema only — no UI in POC.
- **Live-service games:** no "phase" field (pre-launch vs live ops). Contribution dates already carry that information.
- **Cancelled/unannounced projects:** future feature (not in POC) — a contribution attached to a *company only*, with no game. The schema supports it natively because `game_id` on contributions is designed nullable (POC UI still requires a game).
- **Game images (covers/artworks) are never stored by us.** Served directly from IGDB/Steam CDNs (copyright exposure reduction + zero storage).

### 3.2 Companies

- Flat entity + nullable `parent_company_id` + an alias table for name search ("Square" finds "Square Enix"). No full merger/renaming history.
- Companies are imported on-demand from the game source data (IGDB `involved_companies`), same read-only rules as games.
- **Two distinct company relations, never conflated:**
  - Game ↔ company: developer/publisher/porting/support — comes from IGDB, stored in a `game_companies` link table.
  - Person ↔ company: the person's *employer* for a contribution — declared by the person.
- **Company page = aggregation**, not an editable wiki: facts (games, contributors) are computed from source data and contributions. A future "claim" flow (out of POC) will let a verified company edit only its showcase part (logo, description, links) — never the facts. `claimed_by` column exists from day one, dormant. Claim verification: domain email + manual fallback (future).
- **Layoff waves visibility:** the company page does NOT surface temporal aggregates of departures ("50 people left in March"). Deducible from raw data, but not featured. (Product decision, revisitable.)

### 3.3 Contributions (the heart of the model)

A contribution = **(person, game, optional employer company, discipline, free-text job title, start date, end date)**.

- **Model B ("triplet with optional company")** was chosen over person↔game only (too poor: can't represent outsourcing, freelancing, unannounced projects) and over separate employment+assignment objects (academically correct but doubles input friction — friction is the #1 product risk).
- The company on a contribution is the person's **employer** (e.g. "worked on Dark Souls, at Virtuos" — outsourcing is a huge, invisible part of the industry and exactly the audience this platform serves). The game's own developer/publisher comes from IGDB separately.
- **Job title: two fields.** A normalized `discipline` (closed list of ~10–12: Programming, Design, Art, Audio, Production, QA, Writing, Localization, Marketing/Publishing, Support/Other — inspired by IGDA credit standards; the person picks it themselves) + a free-text `job_title` ("Senior Gameplay Programmer"). Discipline powers recruiter filtering; free text preserves fidelity. Future: hierarchical sub-disciplines via FK migration.
- **Multiple contributions per (person, game) are allowed** (promotion mid-project, left and came back). Simply no unique constraint.
- **Dates: month + year precision** (stored as regular DATE columns with day forced to 01 — native SQL overlap operations matter for the future vouching system). `end_date` nullable = "still working on it".
- No full-time/part-time field in POC (trivial enum migration later).
- **No import of official credits, ever in the POC** (and heavy reservations even later): no ghost/unclaimed profiles. A profile = an account, always, created by the person themselves. This kills the homonym-matching problem and drastically simplifies GDPR (no data about non-registered third parties).
- Contribution `status` enum (`active`/`pending`/`disputed`/`removed`) exists from day one, dormant. `disputed` is never shown publicly; it freezes confirmations during review (future moderation flow).
- **Deferred registration** (added 2026-08-11, spec `docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md`): an anonymous visitor answers "which game did you work on?" at `/declare/`, fills a complete credit, and creates the account last. Because signup auto-logs-in, the credit is written at that moment with `status='pending'` and published by email verification — so the verification mail, routinely opened on another device, carries no state. **This is a scoped relaxation of the email-verified gate**: what the gate protects is that nothing unverified is *published*, and a pending credit is rendered nowhere. `/credits/new/` keeps the gate unchanged, so a member who signs up the ordinary way still cannot add a credit before verifying. Nobody may record anything about another person: the funnel only ever writes the visitor's own credit. The funnel's steps and mechanism are untouched by the 2026-08-20 reorder below — only where an anonymous visitor first meets the question changed, from the home page itself to `/declare/`.

### 3.4 People

- **Display name is free** (real name or pseudonym — never require real identity; documented harassment risks in this industry). Credibility will come from peer confirmations, not names.
- Email verification is **required before creating any contribution** (first anti-spam line, foundation of the future trust system).
- **Three visibility booleans:**
  - `profile_public` — default **true**. False = invisible everywhere (safety valve for harassment/temporary withdrawal). The only one enforced beyond defaults in early POC.
  - `contactable` — default **true**. Contact only via relay; email never displayed anywhere, even opt-in (scraping is irreversible).
  - `open_to_work` — default **false**. Pure market signal, active declaration, shown as a badge, filterable in recruiter search. Distinct from `contactable`: someone employed can stay reachable without broadcasting availability to their current employer.
- Signup consent copy must state clearly: *"Your profile and credits will be public and accessible to recruiters — that is the point of the platform."*
- The `contactable` toggle must be easy to find on the profile page (assumed default vs dark pattern = ease of exit).
- **Work gallery** (added 2026-08-20, spec `docs/superpowers/specs/2026-08-20-profile-gallery-design.md`): a profile carries a "Work" gallery, up to 12 images with an optional caption each, newest first, shown after the credits list. Managed from profile edit, not the profile page itself. Verified accounts only — the same email-verification gate as creating a contribution.
- **Every uploaded image goes through one hardened server-side pipeline** (same spec), gallery and avatar alike: re-encoded to WebP, EXIF/GPS metadata stripped, SVG kept structurally impossible (the check reads the decoded format, never the filename or declared header), 10 MB and 40 MP caps enforced before the image is decoded, random filenames. No raw upload is ever stored.
- **Profile card and share row** (added 2026-08-21, spec `docs/superpowers/specs/2026-08-21-open-graph-cards-design.md`): a public profile has a generated 1200×630 card (`/u/<slug>/card.png`) showing exactly what search result cards already show — display name, latest job title, the `credits_count`/`games_count`/years stats, location, "Open to work" — nothing more, no email, no non-`active` credit. **A private profile's card 404s for everyone, owner included**: the networks that fetch `og:image` carry no session, so there is no owner exemption to carve out here (contrast the profile page itself, which does exempt the owner). The 404 is immediate on the server, but cards are served `Cache-Control: public, max-age=3600`, so a browser or CDN that already fetched the PNG may keep serving it for up to an hour after the profile goes private — accepted: the window is bounded, and the card only ever carried data that was public at fetch time. A name with characters Inter doesn't cover (CJK, Arabic, Devanagari…) renders the neutral default card instead of `.notdef` boxes — a Noto fallback chain is deferred (v2). The owner, and only the owner, sees a share row under their profile: copy link, LinkedIn / Bluesky / X, and a preview of their own card; a private profile shows a notice to make it public instead of the row.
- Account deletion removes the gallery's image files, not just the DB rows; the personal-data JSON export (§3.7) lists the portfolio.

### 3.5 Trust / vouching (schema only — NOT in POC)

Designed now so the schema doesn't need surgery later:

- Only users with a contribution on the same game can vouch (target: weight votes by the voter's own confirmation level — "PageRank of trust").
- **Positive confirmations only + private "report" button.** No public negative votes (harassment weapon).
- **No numeric public score.** Public display = factual badges per contribution: "Confirmed by N peers" / "Declared". Internal score for recruiter-search ranking may come later, never displayed.
- Unverified contributions are **visible** with a "Declared" badge.
- `vouches` table exists from day one, empty, with `voter_id` **nullable** (account-deletion anonymization, see 3.7).

### 3.6 Recruiters (IN the POC)

Rationale for inclusion: candidate motivation depends on believing the recruiter side exists. The POC must test the full two-sided loop. The search itself became cheap thanks to the local seed (SQL joins, no external services).

- **Search open to everyone** (changed 2026-07-16, spec `docs/superpowers/specs/2026-07-16-open-recruiter-search-design.md`): the platform is 100% free for now, so the search is not gated — anonymous visitors included. Showing workers that the recruiter-side tool exists is part of the promise, and gating hid it from exactly the people whose motivation depends on believing it exists.
  - **Anti-scraping mitigations are the IP rate limit** (same `SEARCH_RATELIMIT` as the public search), **pagination, and `profile_public`** — see docs/02-ARCHITECTURE.md §5, which already concedes public pages can't be fully protected: accept and mitigate.
  - The form's **≥1-filter rule is a UX guard, not a security boundary.** It stops the accidental filterless submit; it does **not** prevent enumeration and must not be documented as if it did. `?min_rating=1` is a perfectly legal filter that matches nearly everyone — any range filter at its extreme is a no-op, and there is no principled line between "no-op" and "merely broad".
- **Recruiter account (dormant)**: the manual-validation application flow (mini form: name, company, work email, LinkedIn link → admin approves one by one; `role` field on user: `member`/`recruiter`/`admin`; application `pending`/`approved`/`rejected`) stays in place and working, but **no longer gates anything**. Kept cheap to re-arm if paid recruiter accounts return.
- **Recruiter search filters:** discipline × game engines (multi, OR within) × game genres (multi, OR within) × person's country (multi) × game rating (Steam positive % **or** IGDB rating, whichever the game carries) × dates/years of experience × `open_to_work`. ⚠️ **Known data gap (2026-08-12):** the current upstream IGDB export carries no ratings and no genre names, so IGDB-only games (~57% of the catalog) have neither — any rating or genre filter silently excludes people whose matching credits are on non-Steam games. Tracked in ROADMAP.md "Known follow-ups"; the real fix is upstream (add rating/genre columns to the export). The **credit-level** facets cross within a **SINGLE** contribution ("Unreal × Programming" means one credit is both); country and `open_to_work` are person-level. Rating filters on 1–100 (blank, not 0, is how you say "I don't care" — 0 would mean "must *have* rating data"). Engines/genres/countries are picked through an htmx typeahead (chips), not exhaustive checkbox lists. Results ordered by display name; rating is a filter among others, **never a default sort** (penalizes talented people on failed games). **The form lays out as two labelled rows** (changed 2026-08-21, spec `docs/superpowers/specs/2026-08-21-search-chrome-design.md`): **Games they worked on** (engines · genres · min. rating) and **About the person** (discipline · countries · worked on a game since · open to work only) — every filter visible without scrolling on a laptop screen. The per-field "any of the selected" and Steam-only-data help texts are gone; the data caveat now surfaces once, as a single footnote under the rows.
- **Result cards** show the matching credits (up to 3, then "+N more"), the person's "City · Country", career stats over *all* their active credits (credits · distinct games · years active, open end = "present"), and engine repartition % across credited games carrying engine data — rendered under an explicit "Engines on credited games" label, so it reads as a fact about the games rather than a proficiency score. All factual: **no person-level score**, and no email, ever.
- ⚠️ **2D/3D filter caveat:** IGDB has no direct 2D/3D field (only player perspectives/keywords). Treat as best-effort or defer; do not block on it.
- "Knows Unreal" is **not** inferred as a skill. The recruiter filters on two true facts crossed: "worked on an Unreal game" × "discipline = Programming". No self-declared skills in POC.
- **Contact via relay form** (mandatory corollary of search): if `contactable`, a **`Message` button** (renamed from "Contact" 2026-08-21, spec `docs/superpowers/specs/2026-08-21-search-chrome-design.md`, on the profile and on search result cards — the relay endpoint and its form's own title stay "Contact", since that page still is one) sends the message to the person's email without exposing it. Reply-To = recruiter's address, so replies happen directly off-platform by the person's active choice. Rate limiting per sender stored in DB (doubles as abuse traceability). **The sender must be email-verified** (added 2026-08-12): the relay sends mail from our domain with a sender-controlled Reply-To, so it sits behind the same verification gate as contributions — an address the sender never proved they own must not become a Reply-To.
- **The people search IS the home page** (changed 2026-08-11, spec `docs/superpowers/specs/2026-08-11-home-is-people-search-design.md`; reordered 2026-08-20, spec `docs/superpowers/specs/2026-08-20-mobile-first-surface-design.md`). The separate public "For recruiters" promise page is deleted: once the search itself is the root, the tool is its own proof that the recruiter side exists. Its honest-counts commitment is not transferred — no counter is displayed anywhere, which cannot be inflated. The home page leads with the filter form for **every** visitor, member and anonymous alike. For anonymous visitors only, one line above the form (**"Worked on a game? Add your credit"** — trimmed 2026-08-21, spec `docs/superpowers/specs/2026-08-21-search-chrome-design.md`, from the earlier "... — no account needed to start."; still one translation unit, not fragmented around the link) links to the declare funnel at `/declare/`; the nav's primary CTA carries the same label, **`Add your credit`**, and is the bar's one solid button — `/credits/new/` when logged in, `/declare/` when anonymous — outranking `Log in`. **Superseded order: the 2026-08-11 deferred-registration-funnel spec put the funnel's "which game did you work on?" question first, ahead of the search, for anonymous visitors; the 2026-08-20 mobile-first-surface spec reversed it — filters lead again for everyone, and the funnel keeps its full question and form, but only at its own `/declare/` URL.** `robots.txt` no longer carves anything out of the `/search/` disallow; instead `Disallow: /*?` keeps the filter-URL space out of the index while `/` stays crawlable — partial coverage by design, since only wildcard-aware crawlers honor it (see `config/sitemaps.py`). The recruiter application flow keeps working but loses its last inbound link, which is what dormant looks like.
- **Latest-credits feed** (added 2026-08-20, spec `docs/superpowers/specs/2026-08-20-mobile-first-surface-design.md`): before any search runs, the bare front door shows the ten most recent `status='active'` credits belonging to `profile_public=True` users, under a "Latest credits" heading — social proof on an otherwise-empty first visit. Same privacy guards as everywhere else in the product: only active credits, only public profiles, and no timestamp beyond the credit's own dates (a "2 hours ago" would advertise activity patterns). Submitting a search replaces the feed with the results section in place; the filter form posts to `#results` so the viewport lands on results instead of at the top of a full filter stack.
- **Credit dates display as `MM/YYYY` sitewide** (changed 2026-08-20, same spec): profile, game, search-result and feed date ranges all read like `08/2024–03/2025` (`present` for an open end). Career-summary ranges on result cards (`2021–present`) and game release years stay years — they are years, not month/year contributions. Entry keeps the native `<input type="month">`, which localizes to each visitor's own browser locale.
- **About page** (`/about/`, added 2026-08-20, same spec), linked from the footer next to Terms/Privacy: states the mission (a public credits register for the game industry; the 2024+ layoff waves are why the worker side exists), data provenance (the games catalog seeds from IGDB and Steam-derived data; credits are declared by the people themselves, never scraped), the AGPL v3 license with a link to the repo, and contact/safety (the relay principle — personal emails are never exposed — plus a link to the report form).
- **Link previews** (added 2026-08-21, spec `docs/superpowers/specs/2026-08-21-open-graph-cards-design.md`): a Rollcall link pasted on LinkedIn, Bluesky, X, Discord or Slack used to render as a bare URL — no `og:*`/`twitter:card` tags anywhere. Every page now carries them (site defaults from a context processor), with profile and game pages overriding title, description and the `og:image` — a server-rendered, text-only 1200×630 PNG (Pillow, vendored Inter; see docs/03-TECH-STACK.md), never a screenshot or an uploaded asset. The image URL carries a `?v=` token derived from the underlying data, so a changed profile or game gets a new URL and the networks — which cache `og:image` for days — fetch a fresh one instead of a stale one. Same privacy rule as everywhere: a non-public profile 404s for crawlers exactly like it 404s for visitors, so its tags are never seen; no tag, on any page, ever carries an email. See §3.4 for the profile card's content and the owner's share row.
- Out of POC, firm: payment, automated recruiter verification, internal messaging with threads.

### 3.7 GDPR & legal (shapes the schema)

- Explicit consent at signup with clear purposes. Hosting: **EU regions of US-owned providers** (Railway + Cloudflare R2 — see ROADMAP/DEPLOY), so the GDPR file needs signed DPAs/SCCs rather than the "no extra-EU transfer paperwork" shortcut an EU-owned PaaS would have given. (Decision changed from the original Scalingo/Scaleway default.)
- Signup discloses whether an email is already registered (standard Django unique validation); password reset deliberately does not. Accepted for the POC — revisit if account-existence privacy becomes a requirement.
- **Account deletion works in the POC:** contributions → hard cascade delete; vouches *emitted* by the deleted user → anonymized (`voter_id` set NULL), preserving the trust graph of innocent third parties. Hence nullable `voter_id` from day one.
- Personal data export (JSON) in the POC (portability).
- No data about non-registered people in the DB (guaranteed by "no credits import").
- Report/flag page in the POC (host status / DSA diligence). No public accusatory user-generated content anywhere by design.
- **Code license: AGPL v3** from commit 1 (deters closed SaaS forks; Mastodon/Forgejo precedent). Users own their data; platform gets a non-exclusive license via ToS. Do NOT promise an open data license now (irreversible, tension with right to erasure).
- **Before the seed runs:** data agreements in place for each source the operator loads. The seed reads the operator's prepared parquet; see `04-DATABASE-SCHEMA.md` §13 for the write surface.

## 4. POC scope (final)

### In the POC
- Accounts (email + password, free display name, email verification gate before contributing)
- Games DB seeded from the Hushcrasher parquet (weekly upsert job); missing games handled manually at first
- Contributions: game + optional company + discipline + free job title + month/year dates (open end), multiples allowed
- Person page (credits with dates); game page (contributors) — same table read both ways
- Simple search (games, people), open to all
- Recruiter search with filters (discipline, engines, genres, country, rating, dates, open_to_work) — **open to all** since 2026-07-16 (§3.6)
- Recruiter application form + manual validation (Django admin is enough) — dormant since 2026-07-16: still works, gates nothing
- Contact relay form (honors `contactable`)
- Anonymous-visitor pitch line linking to the declare funnel on the home page (the people search at `/` is the recruiter-facing surface; this line carries the promise the old "For recruiters" page used to)
- Account deletion (cascade + anonymization) + JSON export
- Report/flag page
- UI in **English only**, but all strings through Django i18n from day one

### In the schema, no UI (dormant)
`parent_game_id` · `vouches` table (nullable `voter_id`) · `status` on contributions · `claimed_by` on companies · company alias table · `contactable`/`open_to_work` behavior beyond storage if time is short

### Explicitly out of POC
Vouching/confirmations · company claim · manual game creation · internal messaging · payments · automated recruiter verification · moderation workflow beyond the report form · sub-disciplines · skills

### Success metric (two-sided)
1. Industry people, not individually solicited, create an account and declare ≥1 complete contribution.
2. A few real recruiters find the search, run searches, and send contact requests. (Reworded 2026-07-16: the old metric was "apply, get approved, run searches" — the apply/approve step is dormant since the search opened to all, so it can no longer be the signal. Sending a contact request still requires an account, which is the point where a recruiter becomes visible to us.)

### Fallback if the schedule slips
Ship the home page's people search — its anonymous-visitor pitch line already carries the promise — + contact relay first; advanced filters a few weeks later. The promise stays credible.

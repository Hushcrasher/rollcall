# GitHub Integration on Member Profiles — Design

**Status:** approved, ready for implementation plan
**Date:** 2026-07-15

## Goal

On a member's public profile, show a **"Public side projects"** block driven by
their public GitHub activity: number of public repositories and commit counts
per year (current year + up to 5 years of history). It is an *additive,
optional* signal — its presence is a plus, its absence means nothing.

**POC scope:** no OAuth, no ownership verification. The member pastes their
GitHub profile URL in settings; we trust it, same model as a LinkedIn link.
This is an intentional, accepted risk for the POC.

### Framing (non-negotiable, spec §6)

The block is labelled **"Public side projects"** — never "activity level" or
"development activity". The games industry runs on Perforce (Helix Core) and
private internal repos under NDA; an experienced AAA gameplay programmer very
often has an empty GitHub. Framing this as a skill/activity indicator would
penalise exactly the most experienced profiles. Absence means nothing.

## Where it lives

Everything goes in the **`accounts`** app — it is a profile feature — mirroring
how `games/igdb.py` keeps the IGDB external-API client inside the app that owns
its domain.

| File | Responsibility |
|---|---|
| `accounts/models.py` | `User.github_login` field + `GitHubSnapshot` + `GitHubYearlyContribution` |
| `accounts/github.py` | `extract_login()` parser · `GitHubClient` (REST + GraphQL, `_http` isolated) · `get_github_activity()` cache-aside service |
| `accounts/views.py` | `github_activity(request, slug)` htmx fragment endpoint |
| `accounts/urls.py` | route `u/<slug>/github/` |
| `templates/accounts/_github_block.html` | rendered block + its states |
| `accounts/forms.py` | `github_url` field on `SettingsForm` |
| `config/settings/{base,test}.py` | `GITHUB_TOKEN` env (blank in test) |

## Data model

```
User.github_login   CharField(max_length=39, blank=True, default="")   # the declared handle

GitHubSnapshot            # OneToOne(User), the profile-level cache
  login                text
  avatar_url           text (URL)
  public_repos         int, null
  followers            int, null
  account_created_at   datetime, null
  profile_fetched_at   datetime, null      # 24h TTL anchor
  status               enum: never_fetched | ok | not_found | error
  last_error           text, blank

GitHubYearlyContribution  # per (user, year)
  user                 FK(User)
  year                 int
  total_commits        int
  total_contributions  int
  private_count        int                 # restrictedContributionsCount, shown separately
  fetched_at           datetime
  is_final             bool                # year < current_year → never refetched
  UNIQUE(user, year)
```

**Deliberate deviation from spec §4:** the declared handle lives on
`User.github_login`, not only on the snapshot. This separates the *input*
(stable, edited in settings) from the *derived cache* (snapshot + yearly rows).
Changing or clearing `github_url` in settings **deletes the snapshot + yearly
rows**, forcing a clean cold fetch for the new handle — the simplest correct
invalidation. `GitHubSnapshot.login` records the handle a snapshot was fetched
for.

## URL parsing — `extract_login(raw) -> str | None`

Accept: `https://github.com/torvalds`, `github.com/torvalds`, trailing slash,
and a bare `torvalds`.

Algorithm: strip whitespace → strip scheme → if the string contains
`github.com`, take the **first path segment** after it → else treat the whole
string as a bare login → validate against
`^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$`.

- **Repo URLs** (`github.com/user/repo`): keep the first segment (`user`) —
  decided over rejecting, to be forgiving of pastes with extra path.
- Invalid or unextractable → `None`. The form raises a `ValidationError`.
- Empty input is allowed → clears the handle.

## Client — `GitHubClient` (mirrors `IGDBClient`)

- `configured` = `bool(token)`. The client **never runs tokenless** (60 req/h
  anonymous is unusable; GraphQL requires a token regardless).
- `get_profile(login)` → REST `GET https://api.github.com/users/{login}`,
  headers `Authorization: Bearer {token}`, `Accept: application/vnd.github+json`.
  Fields kept: `public_repos`, `followers`, `created_at`, `avatar_url`.
- `get_contribution_years(login)` → GraphQL step A
  (`contributionsCollection { contributionYears }`).
- `get_year_contributions(login, year)` → GraphQL step B, window
  `YYYY-01-01T00:00:00Z … YYYY-12-31T23:59:59Z` (GraphQL caps at a one-year
  window per call → loop year by year). Reads `totalCommitContributions`,
  `restrictedContributionsCount`, `contributionCalendar.totalContributions`.
- `_http()` is the single isolated network method (tests stub it → zero
  network). It logs `x-ratelimit-remaining` and `x-ratelimit-reset`.
  Per-request timeout ~4s.
- Errors: `GitHubError` (base), `GitHubNotFound` (404),
  `GitHubRateLimited` (403/429, carries `x-ratelimit-reset`).

Single server-side token: classic PAT, `read:user` scope, in `GITHUB_TOKEN`.
Never client-side.

## Cache-aside service — `get_github_activity(user)`

Refresh is lazy, on profile view (no cron). Core rule: **past years are
immutable** → fetched once, `is_final=True`, never refetched. Only the current
year carries a 24h TTL, so a typical warm refresh is **one** GraphQL call.

```
no github_login              → None (no block rendered)
client not configured        → None (block hidden; never expose config state publicly)
no snapshot (cold)           → REST profile + years + per-year (last 5 yrs);
                               persist snapshot=ok, yearly rows, is_final = year < current
current-year row missing or >24h old → REST profile + current year only (1 GraphQL call)
fresh                        → serve from DB, no network
status=not_found, <7 days     → serve "not found" state, no retry
any refresh error            → log; PREFER serving stale data if present; else error state
```

Current year = `timezone.now().year`. History capped at the last 5 years to
bound calls.

**Out of scope (POC):** cache stampede — N simultaneous cold views fire N
identical fetches. Documented, not handled. If traffic grows: a
`fetch_in_progress` flag or a Redis lock so one fetch goes out while others
serve stale.

## View + template (non-blocking)

The profile page renders immediately with local data. When
`profile_user.github_login` is set, the profile template includes:

```html
<section hx-get="{% url 'accounts:github_activity' profile_user.slug %}"
         hx-trigger="load" hx-swap="outerHTML"><p>Loading GitHub activity…</p></section>
```

`github_activity(request, slug)`:

- resolves the profile user with the **same queryset rule as `ProfileView`**
  (honours `profile_public`; 404 otherwise);
- calls `get_github_activity()`;
- is wrapped so it **can never 500 the fragment** — worst case it swaps in a
  quiet error/degraded state;
- renders `accounts/_github_block.html`.

Block contents (**core + light context**): avatar, public repo count,
followers, "on GitHub since YYYY", commits-per-year (simple bars/list), and a
separate labelled line **"+N private contributions (last 5y)"** when
`restrictedContributionsCount` is present. Empty accounts (0 repos / 0 commits)
render honestly — not hidden. Never shows the account's email or any private
field.

## Error handling

No GitHub error may break the profile page (the block loads separately, so the
page is already safe; the fragment additionally degrades):

| Case | Behaviour |
|---|---|
| 404 user not found | `status=not_found`, show "GitHub profile not found", no retry for 7 days |
| 403 / 429 rate limited | serve cache even if stale, log, back off to `x-ratelimit-reset` |
| Timeout (>~4s) / 5xx | serve cache even if stale, else hide the block |
| Empty account (0/0) | show the real state |

Always prefer serving stale data over showing nothing.

## Settings form

Add a form-only `github_url = forms.CharField(required=False)` to `SettingsForm`
(a `ModelForm` on `User`; `github_url` is not a model field):

- `clean_github_url` runs `extract_login`; empty is allowed (clears);
  invalid raises `ValidationError`.
- initial value prefilled from the existing `github_login`.
- on save, set `user.github_login`; **if it changed or was cleared, delete the
  existing `GitHubSnapshot` + `GitHubYearlyContribution` rows** to force a clean
  re-fetch.

## Config

- `base.py`: `GITHUB_TOKEN = env("GITHUB_TOKEN", default="")`.
- `test.py`: `GITHUB_TOKEN = ""` (no accidental network; tests stub `_http`).
- `DEPLOY.md`: document the classic PAT (`read:user` scope, server-side only).

## Testing (test-first, matching the repo's TDD discipline)

- **Parser:** table of all accepted forms, repo URL → first segment, invalid → `None`.
- **Client** (stubbed `_http`, zero network): REST profile mapping; GraphQL
  years; per-year window `from`/`to` strings; 404 → `GitHubNotFound`; 403 →
  `GitHubRateLimited`; rate-limit header logging.
- **Service (cache-aside):** cold → N calls + rows persisted with correct
  `is_final`; fresh → 0 calls; stale current-year → exactly 1 partial call;
  past years never refetched; `not_found` 7-day no-retry; error serves stale.
- **View:** renders the block; never 500s (error → degraded partial); hidden
  without a login; respects `profile_public`; never leaks email.
- **Form:** valid URL saves login; repo URL keeps first segment; invalid errors;
  clearing wipes snapshot + yearly rows.
- **Presentation:** private count shown separately/labelled; empty account (0/0)
  rendered honestly.

## Out of scope (decisions already made, spec §7)

- OAuth / ownership verification — no (accepted POC risk).
- Perforce — technically impossible (no central host, per-studio private servers
  under NDA). Do not explore.
- MobyGames API — dropped for the POC (ToS forbids direct competition; they have
  a competing "Professional" tier).
- Cache stampede protection — documented above, not built.

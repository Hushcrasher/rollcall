# IGDB fallback: automatic on a catalogue miss, anonymous funnel included — design

> Status: proposed 2026-08-22, decisions validated with the product owner the
> same day. No model change, no migration. One new setting, one new cached
> helper, two call sites. **It amends a rule of
> [2026-08-11-deferred-registration-funnel-design.md](2026-08-11-deferred-registration-funnel-design.md)** —
> see §4.

## Problems

1. **The fallback is invisible.** On `/credits/new/` the IGDB path exists, but
   it is an italic line — `Not it? Search IGDB for "…"` — under
   `No games found locally.`, and nothing happens until it is clicked. A member
   who does not notice it concludes the game does not exist.
2. **The anonymous funnel has no IGDB path at all**, by design of the 2026-08-11
   spec. `/declare/` is what the nav's `Add your credit` opens for a signed-out
   visitor, so it is the *first* place a missing game is met — and there it is a
   dead end that offers signup. On 2026-08-22 the owner searched
   "Slay the Spire" there, got `No match.`, and concluded the IGDB integration
   had been lost. It had not; it was simply never on that page.
3. **`igdb_search` carries no quota of its own.** It is `@login_required` and
   metered by nothing. Every other search endpoint in `search/views.py` is rate
   limited; this one calls a third party's API.

*(The same session also found the local catalogue empty of real games — that
was a dev-database problem, fixed by running `seed_games` against the prepared
parquet, and is not what this spec is about.)*

## Decisions

| Question | Decision |
|---|---|
| When does IGDB run | **Automatically, whenever the local search returns zero rows** — and only then |
| Anonymous visitors | **Yes** — the declare funnel queries IGDB too |
| What protects the API | A **24 h server-side cache** on the normalised query, plus a **dedicated per-IP quota** (`IGDB_RATELIMIT`, default `10/m`), independent of `SEARCH_RATELIMIT` |
| Importing | Still a **deliberate pick**. `games:igdb_import` stays POST and stays login-gated; the funnel imports server-side, on its own POST |
| When it cannot run | **Degrade silently** to today's copy — never an error page, never a 403 |
| Companies | **No IGDB company search.** The seed covers them (§6) |

## 1. `games/igdb.py` — a cached search

```python
def cached_search(query: str, limit: int = 10) -> list[dict[str, Any]]
```

- **Normalisation:** `strip()`, collapse inner whitespace, `casefold()`. Cache
  key `igdb:search:<sha1(normalised)>` — hashed because an IGDB query is
  arbitrary user text and a cache key is not.
- **Timeout 24 h.** The catalogue this backstops refreshes weekly; a day-old
  answer to "is this game on IGDB" is not stale in any way that matters.
- **An empty result is cached too.** Repeated misses are precisely the traffic
  worth suppressing: a game that is on neither Rollcall nor IGDB will be
  searched again by the next person who types the same thing.
- **Backend:** `CACHES["default"]` — Redis in prod (with `IGNORE_EXCEPTIONS:
  True`, so an unreachable Redis returns `None` and the search simply runs
  live), LocMem in dev and tests.
- **Timeout on the wire drops to 4 s for search.** `_TIMEOUT = 10` stays for
  `get_game` (the import path, one deliberate click); `search_games` gets
  `_SEARCH_TIMEOUT = 4` passed through to `_http`, because this call now
  happens inside a page render and must not hold a worker for ten seconds.
- `IGDBError` is raised as today. Callers catch it; none of them let it escape.

`_igdb_label()` moves from `games/views.py` to `games/igdb.py` and loses its
underscore — `igdb_label()`: it formats an IGDB payload rather than a view's
context, and it now has two callers in two apps, so it is part of the module's
surface.

## 2. `IGDB_RATELIMIT` — a quota that skips, not one that blocks

New setting in `config/settings/base.py`, documented in `.env.example` next to
the other limits:

```python
IGDB_RATELIMIT = env("IGDB_RATELIMIT", default="10/m")
```

Separate from `SEARCH_RATELIMIT` on purpose: the local trigram search is cheap
and ours to spend, an IGDB call is a third-party quota we do not own (Twitch
allows 4 requests/second across the whole application).

Checked with the helper the funnel and the people search already use:

```python
is_ratelimited(request=request, group="igdb_search", key="ip",
               rate=settings.IGDB_RATELIMIT, increment=True)
```

**Two properties that differ from every other limit in this codebase, and are
the reason this section exists:**

- **It never blocks.** `block=True` / `raise Ratelimited` would 403 a page
  whose local results are perfectly fine. Reaching the quota must *skip the
  IGDB call* and fall through to the existing copy. A visitor over quota sees
  the site as it behaves today.
- **A cache hit does not spend quota.** The cache is consulted first; the
  counter is incremented only when a live call is about to be made. Otherwise
  the tenth repeat of a popular query would be refused while costing IGDB
  nothing.

`RATELIMIT_FAIL_OPEN = True` is already set project-wide: an unreachable cache
means unmetered IGDB calls, bounded by the 4 s timeout. Accepted — the same
trade-off the project already took for its other limits, and stated here so it
is not a surprise.

**A consequence worth stating plainly, because it is new here.** Every other
surface `RATELIMIT_FAIL_OPEN` applies to is read-only, so "a cache outage
costs metering, not availability" had no real downside to weigh. This quota is
different: it is what bounds the funnel's one anonymous write (§4), the
games-catalogue import. A Redis outage removes that bound along with every
other one project-wide, leaving IGDB's own catalogue and the 4 s wire timeout
as the only limits left on how many games an anonymous visitor can import in a
window. Accepted for the same reason as above — availability over metering —
but recorded here because, for the first time, that trade reaches a write
path rather than only a search.

## 3. `/credits/new/` — automatic, in the same list

`search/_game_options.html` renders local matches, then today's manual trigger.
It gains one branch:

- **No local matches, IGDB configured, non-blank query** → render an
  auto-fetching fragment instead of the manual button:

  ```html
  <div hx-get="{% url 'games:igdb_search' %}?q={{ query|urlencode }}"
       hx-trigger="load" hx-swap="outerHTML">
    <p class="autocomplete-empty">{% translate "Searching IGDB…" %}</p>
  </div>
  ```

  One extra request, fired by htmx when the fragment is swapped in. No new
  JavaScript, and the placeholder means the panel is never briefly empty.
- **Local matches present** → the manual `Not it? Search IGDB for "…"` button
  stays exactly as it is. A search that finds what it was looking for still
  costs zero IGDB calls; the escape hatch is there for a wrong match.

`games.views.igdb_search` keeps `@login_required`, switches to `cached_search`,
and gains the quota check. Over quota it renders `_igdb_options.html` with a
new `error="throttled"` branch: `IGDB search is busy right now — try again in
a minute.` — distinct from `unavailable`, because the two mean different things
to the person reading them.

## 4. `/declare/` — server-side, anonymous

**`DeclareGameView.get_context_data`.** After `search_games`, when the query is
non-blank, the local list is empty and `IGDBClient().configured`:

```python
context["igdb_options"] = [
    {"igdb_id": r["id"], "label": igdb_label(r)} for r in cached_search(query)
]
```

behind the quota check of §2, and inside `try/except IGDBError:` which sets
`context["igdb_error"] = "unavailable"` instead. Never both.

**`declare_game.html`.** Under the local list, when `igdb_options` is present:
a `Not in our catalogue yet` heading, then one `<form method="post">` per
option carrying `<input type="hidden" name="igdb" value="…">` and a submit
styled like the local picks (`.pick`, on `main` since PR #29). The same shape
as the local list, so keyboard and no-JS both work with no extra code. The existing
`Can't find it? Create your account…` line stays as the last resort and is the
only thing shown when IGDB is off, throttled, or down.

**`DeclareGameView.post`.** Before `_picked_game`, handle `igdb`:

1. `isdecimal()` on the raw value, else re-render — the same trap `_picked_game`
   and `game_employers` already guard: `"²"` is a digit to `isdigit()` but
   `int()` rejects it, which would be a 500 on a public page.
2. Meter the same `igdb_search` quota — an import is an IGDB call.
3. `import_igdb_game(igdb_id)`:
   - `IGDBError` → re-render with `igdb_error="unavailable"`;
   - `None` (IGDB has no such game) → re-render with `igdb_error="gone"`;
   - a `Game` → fall into the **existing** picked-game branch, unchanged, so
     the draft write, the employer-invalidation rule and the redirect to
     `declare_details` are shared rather than duplicated.

### The amendment, stated plainly

The 2026-08-11 funnel spec says: *"`igdb_search`, `igdb_import` and
`company_create` stay `@login_required`: a game missing from the catalogue
converts into a signup rather than opening a write endpoint to anonymous
traffic."* This spec **amends that for the game path only**, and the reasoning
is the trade it makes:

- What an anonymous visitor can now cause is **one row in the games catalogue,
  written from IGDB's own data**. No user data, no contribution, nothing about
  a person. The credit itself still cannot be written before signup, and
  `status='pending'` until email verification, exactly as before.
- It reuses the **seed's idempotent upsert keyed on `igdb_id`**, so a repeat is
  an update, not a duplicate — the same guarantee the weekly seed relies on.
- Rows land with `source='igdb_live'`, distinguishable in admin, and the weekly
  seed overwrites their `[source]` columns on its next run.
- It is bounded by the per-IP quota of §2 and by IGDB's own catalogue: a
  crafted POST with an arbitrary id imports a real IGDB game, which is the same
  outcome as picking one from the list. There is no id that makes it do
  something else.
- `company_create` and `igdb_import` **stay `@login_required`**. Only
  `DeclareGameView.post` gains this path, and only for a game.

The alternative — keep the funnel a dead end — was rejected: it is the funnel's
own conversion step, it is where a signed-out visitor first meets the question,
and it is exactly where the owner hit the wall.

## 5. Copy

New strings, all through i18n: `Searching IGDB…`, `Not in our catalogue yet`,
`IGDB search is busy right now — try again in a minute.`, and
`That game is no longer listed on IGDB.` for the `gone` branch.

## 6. Out of scope

- **IGDB company search.** With the catalogue seeded, every studio credited on
  an IGDB or Steam game already exists (149,158 rows), and the existing
  `Not there? Create "<name>"` button covers outsourcing studios IGDB does not
  list. No endpoint, no `igdb_company_id` lookup.
- Asynchronous or background import; arrow-key navigation in the panel (see
  `2026-08-22-autocomplete-dismiss-design.md`); anything about the seed.

## Docs & tests

`docs/01-DESIGN.md` §3.1 (the live fallback is automatic on a miss and open to
the funnel) and §3.3 (the funnel amendment above); `docs/03-TECH-STACK.md` and
`.env.example` (`IGDB_RATELIMIT`); ROADMAP; and a dated amendment note in
`2026-08-11-deferred-registration-funnel-design.md` pointing here.

**Tests** — house TDD, IGDB stubbed by monkeypatching `IGDBClient._http` as
`games/tests/test_igdb.py` already does, with `IGDB_CLIENT_ID`/`SECRET` set
explicitly per test (`config/settings/test.py` blanks them by default):

1. `cached_search` calls `_http` once for two identical queries; `"  Slay The
   Spire "` and `"slay the spire"` share one cache entry.
2. An empty result is cached: the second call makes no HTTP request.
3. `game_autocomplete` with zero local matches renders the `hx-trigger="load"`
   fragment; with matches it renders the manual trigger and no auto-fetch.
4. `igdb_search` over quota renders the throttled message and makes **no** HTTP
   call.
5. A cache hit does not increment the quota (the 11th identical query in a
   minute still answers).
6. `/declare/?q=…` with zero local matches lists IGDB options; with local
   matches it does not touch IGDB at all.
7. `POST /declare/ {igdb: <id>}` imports the game, writes the draft, redirects
   to the details step; posting the same id twice creates no duplicate row.
8. `POST /declare/ {igdb: "abc"}` and `{igdb: "²"}` re-render, no 500.
9. `IGDBError` on the funnel → 200, the unavailable message, and the signup
   line still present.
10. Over quota on the funnel → no IGDB call, signup line shown.
11. IGDB unconfigured → no call, no options, the page is byte-identical to
    today's behaviour.

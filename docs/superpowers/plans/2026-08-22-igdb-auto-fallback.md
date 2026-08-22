# Automatic IGDB fallback — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the local catalogue returns nothing for a game title, query IGDB automatically — on the credit form *and* in the anonymous declare funnel — behind a 24 h cache and a per-IP quota that skips the call rather than blocking the page.

**Architecture:** All IGDB knowledge stays in `games/igdb.py`: the cache, the quota, and the label formatter. Two callers use it — `games.views.igdb_search` (htmx fragment, members) and `contributions.views.DeclareGameView` (server-rendered, anonymous). The credit form fires the fallback with `hx-trigger="load"`, so no new JavaScript is written. The funnel's import path reuses the seed's idempotent upsert.

**Tech Stack:** Django 6, htmx (vendored), django-ratelimit, Django's cache framework (LocMem in dev/tests, Redis in prod), IGDB v4 via Twitch OAuth.

**Spec:** [`docs/superpowers/specs/2026-08-22-igdb-auto-fallback-design.md`](../specs/2026-08-22-igdb-auto-fallback-design.md)

## Global Constraints

- **Every user-facing string goes through i18n** (`gettext` / `{% translate %}`).
- **Python is fully typed.** Annotate every function, method, fixture and test. `uv run ty check` must pass.
- **TDD**: failing test first, watch it fail, then implement.
- **No network in tests.** IGDB is stubbed by monkeypatching `IGDBClient._http` or `IGDBClient.search_games`, the pattern `games/tests/test_igdb.py` already uses. `config/settings/test.py` blanks `IGDB_CLIENT_ID`/`SECRET`, so any test needing IGDB configured must set them.
- **The quota never blocks.** Reaching it skips the IGDB call and falls through to the copy that existed before this feature. It must never raise `Ratelimited`, never 403, never 500.
- **`igdb_import` and `company_create` stay `@login_required`.** Only `DeclareGameView.post` gains an anonymous IGDB path, and only for a game.
- **Commits are DCO signed-off**: `git commit -s`.
- Full toolchain green before every commit: `uv run pytest` · `uv run ruff check .` · `uv run ruff format --check .` · `uv run ty check`. Postgres up: `docker compose up db`.
- Branch `feat/igdb-auto-fallback`, PR at the end; never commit to `main`.

## A hazard to know before you start

**The test cache is process-wide and persists between tests.** `CACHES["default"]` is `LocMemCache`, and nothing clears it between tests today. Every test in this plan that asserts *how many times* IGDB was called will pass alone and fail in a full run unless the cache is cleared. Each affected module therefore gets:

```python
@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    cache.clear()
```

Rate-limit counters live in the same cache, but `RATELIMIT_ENABLE` is `False` in test settings, so `is_ratelimited` short-circuits without touching it unless a test turns it on — which is why existing endpoint tests are unaffected by the new quota.

## File Structure

| File | Responsibility |
|---|---|
| `games/igdb.py` | **Modify.** All IGDB knowledge: client, cache, quota, label. Grows four module-level functions. |
| `config/settings/base.py` | **Modify.** `IGDB_RATELIMIT`. |
| `.env.example` | **Modify.** Document it. |
| `games/views.py` | **Modify.** `igdb_search` uses the cache + quota; `_igdb_label` moves out. |
| `templates/games/_igdb_options.html` | **Modify.** A `throttled` branch. |
| `templates/search/_game_options.html` | **Modify.** Auto-fetch when there are no local matches. |
| `contributions/views.py` | **Modify.** `DeclareGameView` gains the IGDB options and the import path. |
| `templates/contributions/declare_game.html` | **Modify.** Render those options as POST forms. |
| `games/tests/test_igdb.py`, `games/tests/test_igdb_endpoints.py`, `search/tests/test_autocomplete.py`, `contributions/tests/test_declare_game.py` | **Modify.** The eleven tests the spec lists. |
| `docs/01-DESIGN.md`, `docs/03-TECH-STACK.md`, `ROADMAP.md`, the 2026-08-11 funnel spec | **Modify.** Record, and amend the rule this changes. |

Seven tasks, in dependency order. Tasks 1-2 are pure `games/igdb.py` and testable alone; 3-4 finish the member path; 5-6 the anonymous funnel; 7 the paperwork.

---

### Task 1: Cache the search, move the label formatter

**Files:**
- Modify: `games/igdb.py`
- Modify: `games/views.py` (import the moved function; delete the local copy)
- Test: `games/tests/test_igdb.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `igdb_label(result: dict[str, Any]) -> str` — `"Celeste (2018)"`, or just the name when IGDB has no release date.
  - `cached_search(query: str, limit: int = 10, client: IGDBClient | None = None) -> list[dict[str, Any]]` — raises `IGDBError`.
  - `_search_cache_key(query: str) -> str` and `_SEARCH_CACHE_TTL: int` — used by Task 3's `search_options`.

- [ ] **Step 1: Write the failing tests**

Add to `games/tests/test_igdb.py` (add `from django.core.cache import cache` and `from games.igdb import cached_search, igdb_label` to the imports):

```python
@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    # LocMemCache is process-wide and nothing clears it between tests, so a
    # query cached by one test would silently satisfy another's assertion
    # about how many times IGDB was called.
    cache.clear()


def _counting_search(calls: list[str]) -> Any:
    def search(self: IGDBClient, query: str, limit: int = 10) -> list[dict[str, Any]]:
        calls.append(query)
        return [{"id": 40477, "name": "Slay the Spire", "first_release_date": 1548201600}]

    return search


def test_cached_search_calls_igdb_once_for_a_repeated_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(IGDBClient, "search_games", _counting_search(calls))
    assert cached_search("Slay the Spire")[0]["id"] == 40477
    assert cached_search("Slay the Spire")[0]["id"] == 40477
    assert len(calls) == 1


def test_cached_search_normalises_case_and_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two people typing the same title differently must not cost two calls."""
    calls: list[str] = []
    monkeypatch.setattr(IGDBClient, "search_games", _counting_search(calls))
    cached_search("  Slay   The Spire ")
    cached_search("slay the spire")
    assert len(calls) == 1


def test_cached_search_caches_a_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated misses are exactly the traffic worth suppressing: a title on
    neither Rollcall nor IGDB is what the next visitor types too."""
    calls: list[str] = []

    def empty(self: IGDBClient, query: str, limit: int = 10) -> list[dict[str, Any]]:
        calls.append(query)
        return []

    monkeypatch.setattr(IGDBClient, "search_games", empty)
    assert cached_search("nonexistent game") == []
    assert cached_search("nonexistent game") == []
    assert len(calls) == 1


def test_search_uses_the_short_timeout_and_get_game_keeps_the_long_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A search now runs inside a page render and must not hold a worker for
    ten seconds; the import path is one deliberate click and keeps its head
    room."""
    seen: list[float] = []

    def fake_http(
        self: IGDBClient,
        url: str,
        data: bytes,
        headers: dict[str, str],
        timeout: float = 10,
    ) -> Any:
        seen.append(timeout)
        return []

    monkeypatch.setattr(IGDBClient, "_http", fake_http)
    monkeypatch.setattr(IGDBClient, "_get_token", lambda self: "tok")
    client = IGDBClient(client_id="c", client_secret="s")
    client.search_games("x")
    client.get_game(1)
    assert seen == [4, 10]


def test_igdb_label_appends_the_release_year() -> None:
    assert igdb_label({"name": "Celeste", "first_release_date": 1516924800}) == "Celeste (2018)"
    assert igdb_label({"name": "Unreleased"}) == "Unreleased"
```

- [ ] **Step 2: Run them to verify they fail**

```bash
uv run pytest games/tests/test_igdb.py -v
```

Expected: FAIL — `ImportError: cannot import name 'cached_search' from 'games.igdb'`.

- [ ] **Step 3: Implement in `games/igdb.py`**

Add `import hashlib` to the imports. Change the timeout constants:

```python
_TOKEN_CACHE_KEY = "igdb:access_token"
_SEARCH_CACHE_PREFIX = "igdb:search:"
_SEARCH_CACHE_TTL = 60 * 60 * 24  # the catalogue this backstops refreshes weekly
_TIMEOUT = 10
# Search now runs inside a page render (spec 2026-08-22-igdb-auto-fallback §1),
# so it must not hold a worker for _TIMEOUT. get_game keeps the long one: it is
# the import path, reached by one deliberate click.
_SEARCH_TIMEOUT = 4
```

Thread a `timeout` through the two lower methods:

```python
    def _query(
        self, endpoint: str, body: str, timeout: float = _TIMEOUT
    ) -> list[dict[str, Any]]:
        token = self._get_token()
        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        result = self._http(f"{self.API_BASE}/{endpoint}", body.encode(), headers, timeout)
        return result if isinstance(result, list) else []

    def _http(
        self, url: str, data: bytes, headers: dict[str, str], timeout: float = _TIMEOUT
    ) -> Any:
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise IGDBError(f"IGDB request failed: {exc}") from exc
```

and have `search_games` pass the short one — its last line becomes:

```python
        return self._query("games", body, timeout=_SEARCH_TIMEOUT)
```

Then add the module-level functions, after the `IGDBClient` class:

```python
def igdb_label(result: dict[str, Any]) -> str:
    """`"Celeste (2018)"` — the label both callers show for an IGDB match.

    Lives here rather than in a view: it formats an IGDB payload, not a view's
    context, and it has two callers in two apps.
    """
    name = result.get("name", "")
    timestamp = result.get("first_release_date")
    if timestamp:
        return f"{name} ({datetime.fromtimestamp(timestamp, tz=UTC).year})"
    return name


def _search_cache_key(query: str) -> str:
    # Normalised so two spellings of one title share an entry, and hashed
    # because an IGDB query is arbitrary user text and a cache key is not.
    # usedforsecurity=False: this is a cache key, not a digest anyone trusts —
    # without it ruff's S324 flags sha1 and CI fails.
    normalised = " ".join(query.split()).casefold()
    return _SEARCH_CACHE_PREFIX + hashlib.sha1(
        normalised.encode(), usedforsecurity=False
    ).hexdigest()


def cached_search(
    query: str, limit: int = 10, client: IGDBClient | None = None
) -> list[dict[str, Any]]:
    """IGDB search behind a 24h cache keyed on the normalised query.

    The empty list is cached too, deliberately: a title on neither Rollcall nor
    IGDB is exactly what the next visitor will type, and suppressing that
    repeat is most of what this cache is for. Raises IGDBError like the client
    it wraps.
    """
    key = _search_cache_key(query)
    cached = cache.get(key)
    if cached is not None:
        return cached
    results = (client or IGDBClient()).search_games(query, limit=limit)
    cache.set(key, results, timeout=_SEARCH_CACHE_TTL)
    return results
```

- [ ] **Step 4: Delete the copy in `games/views.py`**

Remove the `_igdb_label` function (and the now-unused `from datetime import UTC, datetime` import if nothing else in the file uses it — check first), import the moved one, and update its one call site inside `igdb_search`:

```python
from games.igdb import IGDBClient, IGDBError, igdb_label, import_igdb_game
```

```python
                "options": [
                    {"igdb_id": r["id"], "label": igdb_label(r)} for r in client.search_games(query)
                ]
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest games/tests/ -q && uv run ruff check . && uv run ty check
```

Expected: all pass. `ruff` catches the stale `datetime` import if you left it.

- [ ] **Step 6: Commit**

```bash
git add games/igdb.py games/views.py games/tests/test_igdb.py
git commit -s -m "feat(igdb): cache searches for 24h; move the label formatter

cached_search keys on the normalised query (whitespace collapsed,
casefolded, sha1-hashed because a cache key is not arbitrary user text) and
caches the empty list too — repeated misses are precisely the traffic worth
suppressing.

The search timeout drops from 10s to 4s: it is about to run inside a page
render. get_game keeps 10s, being one deliberate click.

_igdb_label moves from games/views.py to games/igdb.py as igdb_label: it
formats an IGDB payload rather than a view's context, and is about to have
two callers in two apps."
```

---

### Task 2: `IGDB_RATELIMIT` and a quota that skips

**Files:**
- Modify: `config/settings/base.py` (the rate-limiting block)
- Modify: `.env.example`
- Modify: `games/igdb.py`
- Test: `games/tests/test_igdb.py`

**Interfaces:**
- Consumes: Task 1's module.
- Produces: `quota_exceeded(request: HttpRequest) -> bool` — `True` when this IP has spent its IGDB allowance. **Never raises.**

- [ ] **Step 1: Write the failing tests**

Add to `games/tests/test_igdb.py` (imports: `from django.test import RequestFactory`, `from games.igdb import quota_exceeded`):

```python
def test_quota_allows_up_to_the_limit_then_reports_exceeded(settings: Any) -> None:
    settings.RATELIMIT_ENABLE = True
    settings.IGDB_RATELIMIT = "1/m"
    request = RequestFactory().get("/declare/")
    assert quota_exceeded(request) is False
    assert quota_exceeded(request) is True


def test_quota_is_independent_of_the_search_ratelimit(settings: Any) -> None:
    """The local trigram search is cheap and ours; an IGDB call is a third
    party's quota. Spending one must not spend the other."""
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    settings.IGDB_RATELIMIT = "5/m"
    request = RequestFactory().get("/declare/")
    for _ in range(5):
        assert quota_exceeded(request) is False
    assert quota_exceeded(request) is True
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest games/tests/test_igdb.py -k quota -v
```

Expected: FAIL — `ImportError: cannot import name 'quota_exceeded'`.

- [ ] **Step 3: Add the setting**

In `config/settings/base.py`, in the rate-limiting block after `SEARCH_RATELIMIT`:

```python
# IGDB live-fallback quota, per IP. Separate from SEARCH_RATELIMIT on purpose:
# the local trigram search is cheap and ours to spend, while an IGDB call is a
# third-party allowance we do not own (Twitch permits 4 requests/second across
# the whole application). Unlike every other limit here this one does NOT
# block — see games.igdb.quota_exceeded.
IGDB_RATELIMIT = env("IGDB_RATELIMIT", default="10/m")
```

In `.env.example`, under `# Anti-scraping rate limits (optional; per IP)`:

```
IGDB_RATELIMIT=10/m         # live IGDB fallback; over quota = no call, not an error
```

- [ ] **Step 4: Add the helper to `games/igdb.py`**

Imports: `from django.http import HttpRequest` and `from django_ratelimit.core import is_ratelimited`.

```python
_QUOTA_GROUP = "igdb_search"


def quota_exceeded(request: HttpRequest) -> bool:
    """True when this IP has spent its IGDB allowance for the window.

    Two things make this unlike every other limit in the project, and both are
    deliberate (spec 2026-08-22-igdb-auto-fallback §2):

    - **It never blocks.** No `block=True`, no `Ratelimited`. Reaching the
      quota means the caller skips the IGDB call and falls back to the copy
      that existed before this feature — 403-ing a page whose own local
      results are perfectly good would be a worse outcome than not asking a
      third party.
    - **Only call it when a live request is about to be made.** A cache hit
      costs IGDB nothing, so it must not spend quota; callers check the cache
      first.

    RATELIMIT_FAIL_OPEN is already True project-wide, so an unreachable cache
    un-meters rather than 500s — bounded here by the 4s search timeout.
    """
    return is_ratelimited(
        request=request,
        group=_QUOTA_GROUP,
        key="ip",
        rate=settings.IGDB_RATELIMIT,
        increment=True,
    )
```

- [ ] **Step 5: Run to verify they pass**

```bash
uv run pytest games/tests/test_igdb.py -v && uv run ruff check . && uv run ty check
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add config/settings/base.py .env.example games/igdb.py games/tests/test_igdb.py
git commit -s -m "feat(igdb): a per-IP quota that skips the call instead of blocking

IGDB_RATELIMIT (default 10/m), separate from SEARCH_RATELIMIT because the
local trigram search is ours to spend and an IGDB call is Twitch's.

quota_exceeded() returns a bool and never raises: reaching the quota must
skip the third-party call, not 403 a page whose local results are fine.
That is the opposite of every other limit in this codebase, so the reason
is in the docstring."
```

---

### Task 3: `search_options`, and the member endpoint that uses it

**Files:**
- Modify: `games/igdb.py`
- Modify: `games/views.py` (`igdb_search`)
- Modify: `templates/games/_igdb_options.html`
- Test: `games/tests/test_igdb_endpoints.py`

**Interfaces:**
- Consumes: `cached_search`, `_search_cache_key`, `quota_exceeded`, `igdb_label` (Tasks 1-2).
- Produces: `search_options(request: HttpRequest, query: str, client: IGDBClient | None = None) -> list[dict[str, Any]] | None` — a list of `{"igdb_id": int, "label": str}`, or `None` when the quota is spent. Raises `IGDBError`. Both call sites (this task and Task 5) use it.

- [ ] **Step 1: Write the failing tests**

Add to `games/tests/test_igdb_endpoints.py` (imports: `from django.core.cache import cache`):

```python
@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    cache.clear()


def test_search_over_quota_says_so_and_calls_nothing(
    client: Client, member: User, igdb_configured: None, settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over quota is not an error: the fragment says why and no HTTP happens."""
    settings.RATELIMIT_ENABLE = True
    settings.IGDB_RATELIMIT = "0/m"
    calls: list[str] = []
    monkeypatch.setattr(
        IGDBClient, "search_games", lambda self, q, limit=10: calls.append(q) or []
    )
    response = client.get(reverse("games:igdb_search"), {"q": "celeste"})
    assert response.status_code == 200
    assert b"busy right now" in response.content
    assert calls == []


def test_a_cached_search_does_not_spend_quota(
    client: Client, member: User, igdb_configured: None, settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The eleventh repeat of a popular title costs IGDB nothing, so it must
    still answer."""
    settings.RATELIMIT_ENABLE = True
    settings.IGDB_RATELIMIT = "1/m"
    monkeypatch.setattr(
        IGDBClient, "search_games", lambda self, q, limit=10: [{"id": 26226, "name": "Celeste"}]
    )
    url = reverse("games:igdb_search")
    for _ in range(3):
        response = client.get(url, {"q": "celeste"})
        assert b"Celeste" in response.content
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest games/tests/test_igdb_endpoints.py -v
```

Expected: FAIL — `busy right now` is not in the response; the third repeat is not yet quota-aware.

- [ ] **Step 3: Add `search_options` to `games/igdb.py`**

```python
def search_options(
    request: HttpRequest, query: str, client: IGDBClient | None = None
) -> list[dict[str, Any]] | None:
    """IGDB matches for `query` as `{igdb_id, label}` dicts, or None when this
    IP is over quota.

    Cache first, quota second — in that order, so a repeat of a popular query
    keeps answering after the allowance is spent (it costs IGDB nothing). Both
    call sites want exactly this trio (cache, quota, labels), which is why it
    is one function rather than three the callers must remember to combine.
    """
    if cache.get(_search_cache_key(query)) is None and quota_exceeded(request):
        return None
    return [{"igdb_id": r["id"], "label": igdb_label(r)} for r in cached_search(query, client=client)]
```

- [ ] **Step 4: Rewrite `igdb_search` in `games/views.py`**

```python
@login_required
def igdb_search(request: HttpRequest) -> HttpResponse:
    """htmx fragment: search IGDB live for games missing from the seed."""
    client = IGDBClient()
    context: dict[str, Any] = {}
    query = request.GET.get("q", "").strip()
    if not client.configured:
        context["error"] = "unconfigured"
    elif query:
        try:
            options = search_options(request, query)
        except IGDBError:
            context["error"] = "unavailable"
        else:
            # None is "over quota", which is not an error and not an empty
            # result — it needs its own message, or the member reads "no games
            # found on IGDB" about a game that is on IGDB.
            if options is None:
                context["error"] = "throttled"
            else:
                context["options"] = options
    return render(request, "games/_igdb_options.html", context)
```

Update the import line to `from games.igdb import IGDBClient, IGDBError, import_igdb_game, search_options` — `igdb_label` is no longer referenced here.

- [ ] **Step 5: Add the `throttled` branch to the template**

In `templates/games/_igdb_options.html`, between the two existing error branches:

```html
{% if error == "unconfigured" %}
  <p class="autocomplete-empty">{% translate "IGDB search is not configured on this server." %}</p>
{% elif error == "throttled" %}
  <p class="autocomplete-empty">{% translate "IGDB search is busy right now — try again in a minute." %}</p>
{% elif error == "unavailable" %}
  <p class="autocomplete-empty">{% translate "IGDB is unavailable right now — try again later." %}</p>
{% else %}
```

The rest of the file is unchanged.

- [ ] **Step 6: Run to verify they pass**

```bash
uv run pytest games/tests/ -q && uv run ruff check . && uv run ty check
```

Expected: all pass, including the pre-existing endpoint tests.

- [ ] **Step 7: Commit**

```bash
git add games/igdb.py games/views.py templates/games/_igdb_options.html games/tests/test_igdb_endpoints.py
git commit -s -m "feat(igdb): search_options — cache, then quota, then labels

One function, because both call sites want exactly that trio and the order
is the invariant: cache first means a repeat of a popular query keeps
answering after the allowance is spent, since it costs IGDB nothing.

igdb_search distinguishes over-quota from no-results: they are different
facts, and conflating them tells a member 'no games found on IGDB' about a
game that is on IGDB."
```

---

### Task 4: The credit form fetches IGDB by itself on a local miss

**Files:**
- Modify: `templates/search/_game_options.html`
- Test: `search/tests/test_autocomplete.py`

**Interfaces:**
- Consumes: `games:igdb_search` (Task 3).
- Produces: nothing for later tasks.

- [ ] **Step 1: Write the failing tests**

Add to `search/tests/test_autocomplete.py`:

```python
@pytest.fixture
def igdb_configured(settings: Any) -> None:
    settings.IGDB_CLIENT_ID = "cid"
    settings.IGDB_CLIENT_SECRET = "secret"


def test_a_local_miss_fetches_igdb_without_being_asked(
    client: Client, igdb_configured: None
) -> None:
    """The escape hatch used to be an italic line the member had to notice.
    Nothing found locally means the question was already asked — ask IGDB."""
    response = client.get(reverse("search:game_autocomplete"), {"q": "Slay the Spire"})
    assert b'hx-trigger="load"' in response.content
    assert b"Searching IGDB" in response.content


def test_local_matches_keep_igdb_behind_a_deliberate_click(
    client: Client, igdb_configured: None
) -> None:
    """A search that found what it wanted must still cost zero IGDB calls."""
    Game.objects.create(title="Slay the Spire", source=Game.Source.MANUAL)
    response = client.get(reverse("search:game_autocomplete"), {"q": "Slay the Spire"})
    assert b"igdb-trigger" in response.content
    assert b'hx-trigger="load"' not in response.content


def test_a_local_miss_offers_nothing_when_igdb_is_unconfigured(client: Client) -> None:
    """Default test settings blank the credentials — the page must look
    exactly as it did before this feature."""
    response = client.get(reverse("search:game_autocomplete"), {"q": "Slay the Spire"})
    assert b'hx-trigger="load"' not in response.content
    assert b"igdb-trigger" not in response.content
```

Check the top of the file for the imports it already has (`Game`, `reverse`, `Client`); add `from typing import Any` if absent.

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest search/tests/test_autocomplete.py -k igdb -v
```

Expected: FAIL — no `hx-trigger="load"` in the fragment.

- [ ] **Step 3: Split the trailing branch of `templates/search/_game_options.html`**

Replace the whole `{% if igdb_enabled and query %}` block at the end of the file with:

```html
{% if igdb_enabled and query %}
  {% if games %}
    {# Local matches exist, so the search found something: IGDB stays one
       deliberate click, and a search that got what it wanted costs zero
       IGDB calls. #}
    <button type="button" class="igdb-trigger"
            hx-get="{% url 'games:igdb_search' %}?q={{ query|urlencode }}"
            hx-target="closest .results">
      {% blocktranslate %}Not it? Search IGDB for "{{ query }}"{% endblocktranslate %}
    </button>
  {% else %}
    {# Nothing locally: don't make the member find the escape hatch. htmx
       fires this on swap-in; hx-swap="outerHTML" replaces only this div, so
       "No games found locally." above it stays. #}
    <div hx-get="{% url 'games:igdb_search' %}?q={{ query|urlencode }}"
         hx-trigger="load" hx-swap="outerHTML">
      <p class="autocomplete-empty">{% translate "Searching IGDB…" %}</p>
    </div>
  {% endif %}
{% endif %}
```

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest search/tests/test_autocomplete.py -q
```

Expected: all pass.

- [ ] **Step 5: Verify in the browser**

Dev server on port 8010, logged in as a verified member, on `/credits/new/`. Type a title that is not in the catalogue: after the local "No games found locally." the fragment must replace itself with IGDB results without a click. Clicking one still imports and selects it. Then type a title that **is** in the catalogue: the local list appears and no IGDB request is made — confirm in the network panel.

- [ ] **Step 6: Commit**

```bash
git add templates/search/_game_options.html search/tests/test_autocomplete.py
git commit -s -m "feat(search): fetch IGDB automatically when nothing matches locally

The fallback was an italic line under 'No games found locally.' that did
nothing until clicked; a member who did not notice it concluded the game
did not exist.

Zero local matches now render an hx-trigger=load fragment instead, so htmx
asks IGDB on swap-in — no new JavaScript. With local matches the deliberate
click stays, so a search that found what it wanted still costs nothing."
```

---

### Task 5: The anonymous funnel offers IGDB matches

**Files:**
- Modify: `contributions/views.py` (`DeclareGameView.get_context_data`)
- Modify: `templates/contributions/declare_game.html`
- Test: `contributions/tests/test_declare_game.py`

**Interfaces:**
- Consumes: `search_options`, `IGDBClient`, `IGDBError`.
- Produces: context keys `igdb_options` (list of `{igdb_id, label}`) and `igdb_error` (`"unavailable"`, `"throttled"` or `"gone"`), both read by `declare_game.html`. Task 6 sets `igdb_error` too.

- [ ] **Step 1: Write the failing tests**

Add to `contributions/tests/test_declare_game.py` (imports: `from typing import Any`, `from games.igdb import IGDBClient`):

```python
@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    cache.clear()


@pytest.fixture
def igdb_configured(settings: Any) -> None:
    settings.IGDB_CLIENT_ID = "cid"
    settings.IGDB_CLIENT_SECRET = "secret"


def test_a_local_miss_offers_igdb_matches_to_an_anonymous_visitor(
    client: Client, igdb_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The funnel is where a signed-out visitor first meets a missing game.
    It used to be a dead end that offered signup (spec §4)."""
    monkeypatch.setattr(
        IGDBClient,
        "search_games",
        lambda self, q, limit=10: [
            {"id": 40477, "name": "Slay the Spire", "first_release_date": 1548201600}
        ],
    )
    response = client.get(reverse("contributions:declare"), {"q": "Slay the Spire"})
    assert response.status_code == 200
    assert b"Not in our catalogue yet" in response.content
    assert b"Slay the Spire (2019)" in response.content
    assert b'name="igdb" value="40477"' in response.content


def test_local_matches_never_reach_igdb(
    client: Client, game: Game, igdb_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        IGDBClient, "search_games", lambda self, q, limit=10: calls.append(q) or []
    )
    response = client.get(reverse("contributions:declare"), {"q": "Hollow Knight"})
    assert b"Hollow Knight" in response.content
    assert calls == []


def test_igdb_being_down_leaves_the_page_usable(
    client: Client, igdb_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never an error page: the visitor still gets the signup route."""

    def boom(self: IGDBClient, query: str, limit: int = 10) -> list[dict[str, Any]]:
        raise IGDBError("down")

    monkeypatch.setattr(IGDBClient, "search_games", boom)
    response = client.get(reverse("contributions:declare"), {"q": "Slay the Spire"})
    assert response.status_code == 200
    assert b"IGDB is unavailable right now" in response.content
    assert b"Create your account" in response.content


def test_over_quota_falls_back_to_the_signup_line(
    client: Client, igdb_configured: None, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.RATELIMIT_ENABLE = True
    settings.IGDB_RATELIMIT = "0/m"
    calls: list[str] = []
    monkeypatch.setattr(
        IGDBClient, "search_games", lambda self, q, limit=10: calls.append(q) or []
    )
    response = client.get(reverse("contributions:declare"), {"q": "Slay the Spire"})
    assert response.status_code == 200
    assert calls == []
    assert b"Create your account" in response.content


def test_unconfigured_igdb_changes_nothing(client: Client) -> None:
    """Default test settings blank the credentials: byte-for-byte the old
    behaviour."""
    response = client.get(reverse("contributions:declare"), {"q": "Slay the Spire"})
    assert b"Not in our catalogue yet" not in response.content
    assert b"Create your account" in response.content
```

Add `from games.igdb import IGDBError` to the imports.

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest contributions/tests/test_declare_game.py -k igdb -v
```

Expected: FAIL — `Not in our catalogue yet` is absent.

- [ ] **Step 3: Extend `DeclareGameView`**

Add a class attribute and rewrite `get_context_data`; leave every other method as it is.

```python
class DeclareGameView(TemplateView):
    template_name = "contributions/declare_game.html"

    # Set on the instance by the IGDB paths below. Django builds one view
    # instance per request, so this class default is never shared.
    igdb_error: str = ""
```

```python
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        query = self.request.POST.get("q", "") or self.request.GET.get("q", "")
        context["query"] = query
        games = search_games(query) if query.strip() else []
        context["games"] = games
        # IGDB only on a local miss, and only as an offer: everything that can
        # stop it — unconfigured, over quota, IGDB down — leaves the page as it
        # was before this existed (the miss plus the signup line). It is never
        # an error page (spec 2026-08-22-igdb-auto-fallback §4).
        if query.strip() and not games:
            self._offer_igdb_matches(context, query)
        if self.igdb_error:
            # An explicit failure from the import path wins over anything the
            # offer above may have set.
            context["igdb_error"] = self.igdb_error
        return context

    def _offer_igdb_matches(self, context: dict[str, Any], query: str) -> None:
        if not IGDBClient().configured:
            return
        try:
            options = search_options(self.request, query)
        except IGDBError:
            context["igdb_error"] = "unavailable"
            return
        # None is "over quota" — say nothing and let the signup line carry the
        # page, exactly as it did before.
        if options:
            context["igdb_options"] = options
```

Update the import: `from games.igdb import IGDBClient, IGDBError, search_options`.

- [ ] **Step 4: Render the offers in `declare_game.html`**

Inside `{% if query %}`, after the `{% if games %}…{% else %}<p>No match.</p>{% endif %}` block and **before** the "Can't find it?" paragraph:

```html
    {% if igdb_options %}
      <h2>{% translate "Not in our catalogue yet" %}</h2>
      {% comment %}
        The same shape as the local picks above — one POST form per option —
        so keyboard and no-JS both work with no extra code. `q` rides along so
        a failed import re-renders this list instead of an empty page.
      {% endcomment %}
      <ul>
        {% for option in igdb_options %}
          <li>
            <form method="post">
              {% csrf_token %}
              <input type="hidden" name="igdb" value="{{ option.igdb_id }}">
              <input type="hidden" name="q" value="{{ query }}">
              <button class="pick" type="submit">{{ option.label }}</button>
            </form>
          </li>
        {% endfor %}
      </ul>
    {% elif igdb_error == "unavailable" %}
      <p class="muted">{% translate "IGDB is unavailable right now — try again later." %}</p>
    {% elif igdb_error == "gone" %}
      <p class="muted">{% translate "That game is no longer listed on IGDB." %}</p>
    {% endif %}
```

The existing "Can't find it? Create your account…" paragraph stays exactly where it is — it is the last resort and the only thing shown when IGDB is off, throttled or down.

- [ ] **Step 5: Run to verify they pass**

```bash
uv run pytest contributions/tests/ -q && uv run ruff check . && uv run ty check
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add contributions/views.py templates/contributions/declare_game.html contributions/tests/test_declare_game.py
git commit -s -m "feat(declare): offer IGDB matches when the catalogue misses

The anonymous funnel is where a signed-out visitor first meets a missing
game, and it was a dead end that offered signup — searching a well-known
title there looked like the IGDB integration had been lost.

Server-rendered, only on a local miss, as POST forms shaped like the local
picks so keyboard and no-JS both work. Everything that can stop it —
unconfigured, over quota, IGDB down — leaves the page exactly as it was:
the miss plus the signup line. Never an error page."
```

---

### Task 6: Picking an IGDB match imports it and continues the funnel

This is the one anonymous write path. Read the spec's §4 amendment before implementing.

**Files:**
- Modify: `contributions/views.py` (`DeclareGameView.post`, plus one new method)
- Test: `contributions/tests/test_declare_game.py`

**Interfaces:**
- Consumes: `import_igdb_game`, `quota_exceeded`, `IGDBError`, and Task 5's `igdb_error` attribute.
- Produces: nothing for later tasks.

- [ ] **Step 1: Write the failing tests**

```python
def test_picking_an_igdb_match_imports_it_and_moves_on(
    client: Client, igdb_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        IGDBClient,
        "get_game",
        lambda self, igdb_id: {"id": 40477, "name": "Slay the Spire", "genres": []},
    )
    response = client.post(reverse("contributions:declare"), {"igdb": "40477"})
    assert response.status_code == 302
    assert response.url == reverse("contributions:declare_details")
    game = Game.objects.get(igdb_id=40477)
    assert game.title == "Slay the Spire"
    assert game.source == Game.Source.IGDB_LIVE
    assert client.session[SESSION_KEY]["game"] == str(game.pk)


def test_picking_the_same_igdb_match_twice_creates_no_duplicate(
    client: Client, igdb_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It reuses the seed's idempotent upsert, keyed on igdb_id — a repeat is
    an update. This is most of why an anonymous write path is acceptable."""
    monkeypatch.setattr(
        IGDBClient,
        "get_game",
        lambda self, igdb_id: {"id": 40477, "name": "Slay the Spire", "genres": []},
    )
    url = reverse("contributions:declare")
    client.post(url, {"igdb": "40477"})
    client.post(url, {"igdb": "40477"})
    assert Game.objects.filter(igdb_id=40477).count() == 1


@pytest.mark.parametrize("raw", ["abc", "²", ""])
def test_a_junk_igdb_id_does_not_500(client: Client, raw: str) -> None:
    """`²` is a digit to isdigit() but int() rejects it — the same trap
    _picked_game and games.views.game_employers already guard against, on a
    page anonymous traffic can post to."""
    response = client.post(reverse("contributions:declare"), {"igdb": raw})
    assert response.status_code == 200


def test_an_import_that_igdb_no_longer_has_says_so(
    client: Client, igdb_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(IGDBClient, "get_game", lambda self, igdb_id: None)
    response = client.post(reverse("contributions:declare"), {"igdb": "40477", "q": "slay"})
    assert response.status_code == 200
    assert b"no longer listed on IGDB" in response.content


def test_an_import_over_quota_does_not_call_igdb(
    client: Client, igdb_configured: None, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.RATELIMIT_ENABLE = True
    settings.IGDB_RATELIMIT = "0/m"
    calls: list[int] = []
    monkeypatch.setattr(
        IGDBClient, "get_game", lambda self, igdb_id: calls.append(igdb_id) or None
    )
    response = client.post(reverse("contributions:declare"), {"igdb": "40477"})
    assert response.status_code == 200
    assert calls == []
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest contributions/tests/test_declare_game.py -k igdb -v
```

Expected: FAIL — the POST re-renders instead of redirecting; no `Game` is created.

- [ ] **Step 3: Extend `post()` and add the import method**

Change only the first lines of `post`; the draft branch and the two closing lines are untouched:

```python
    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        game = self._picked_game(request)
        if game is None and request.POST.get("igdb"):
            game = self._import_picked_igdb_game(request)
        if game is not None:
            ...  # unchanged draft branch and redirect
        self._meter_search_if_any(request)
        return self.render_to_response(self.get_context_data(**kwargs))
```

Add the method next to `_picked_game`:

```python
    def _import_picked_igdb_game(self, request: HttpRequest) -> Game | None:
        """Import the IGDB game the visitor picked, then behave like a local pick.

        This is the funnel's one anonymous write path, and it amends the rule
        in spec 2026-08-11 that kept these endpoints login-gated. What it can
        cause is one row in the *games catalogue*, written from IGDB's own
        data — no user data, through the seed's idempotent upsert keyed on
        `igdb_id` (so a repeat is an update, not a duplicate), marked
        `source='igdb_live'`, and metered on the same IGDB quota as the search
        that produced the option. `igdb_import` and `company_create` stay
        `@login_required`.
        """
        raw = request.POST.get("igdb", "")
        # isdecimal(), not isdigit(): "²" is a digit but int() rejects it, so
        # isdigit() would raise ValueError -> 500 on a page anonymous traffic
        # posts to. The same guard _picked_game already carries.
        if not raw.isdecimal():
            return None
        if quota_exceeded(request):
            self.igdb_error = "throttled"
            return None
        try:
            game = import_igdb_game(int(raw))
        except IGDBError:
            self.igdb_error = "unavailable"
            return None
        if game is None:
            self.igdb_error = "gone"
        return game
```

Update the import: `from games.igdb import IGDBClient, IGDBError, import_igdb_game, quota_exceeded, search_options`.

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest contributions/tests/ -q && uv run ruff check . && uv run ty check
```

Expected: all pass, the pre-existing funnel tests included — especially `test_a_junk_game_id_does_not_500` and the four rate-limit ones.

- [ ] **Step 5: Verify the whole funnel in the browser**

Logged out, at `/declare/`: search a title absent from the catalogue, pick an IGDB result, and confirm you land on the details step with the employer select already populated from the freshly imported game's studios. Then walk to the account step and check the credit is written `pending` and published on verification — the funnel's existing behaviour must be untouched by this.

- [ ] **Step 6: Commit**

```bash
git add contributions/views.py contributions/tests/test_declare_game.py
git commit -s -m "feat(declare): import the picked IGDB game and continue the funnel

Amends spec 2026-08-11's rule that the funnel's IGDB endpoints stay
login-gated. The trade, argued in spec 2026-08-22 §4: what an anonymous
visitor can cause is one games-catalogue row written from IGDB's own data,
through the seed's idempotent upsert keyed on igdb_id, marked
source='igdb_live', metered on the IGDB quota. No user data. The credit
still cannot be published before email verification. igdb_import and
company_create stay login-gated.

A successful import falls into the existing picked-game branch, so the
draft write, the employer-invalidation rule and the redirect are shared
rather than duplicated."
```

---

### Task 7: Documentation

**Files:**
- Modify: `docs/01-DESIGN.md` §3.1 and §3.3
- Modify: `docs/03-TECH-STACK.md`
- Modify: `ROADMAP.md`
- Modify: `docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md`

- [ ] **Step 1: Amend `docs/01-DESIGN.md` §3.1**

Replace the first bullet's last sentence ("Live IGDB API is only a fallback for very recent games missing from the last refresh (can be handled manually during the POC).") with:

```markdown
Live IGDB API is the fallback for games missing from the last refresh, and since 2026-08-22 (spec `docs/superpowers/specs/2026-08-22-igdb-auto-fallback-design.md`) it runs **automatically whenever a title search returns zero local rows** — on the credit form and in the anonymous declare funnel alike — behind a 24 h cache on the normalised query and a per-IP `IGDB_RATELIMIT` quota that **skips the call rather than blocking the page**. A search that matched locally never reaches IGDB. Unconfigured credentials, a spent quota or an unreachable IGDB all degrade to the behaviour that predates this: the local miss and its signup line.
```

- [ ] **Step 2: Amend `docs/01-DESIGN.md` §3.3**

In the "Deferred registration" bullet, after the sentence about nobody recording anything about another person:

```markdown
**Amended 2026-08-22** (spec `docs/superpowers/specs/2026-08-22-igdb-auto-fallback-design.md`): a local miss in step 1 now offers IGDB matches, and picking one imports the game before continuing — the funnel's one anonymous write path. It writes a games-catalogue row from IGDB's own data through the seed's idempotent upsert (`source='igdb_live'`), never user data, metered on the IGDB quota. `igdb_import` and `company_create` stay `@login_required`.
```

- [ ] **Step 3: Amend the 2026-08-11 funnel spec**

Find the sentence keeping the three endpoints login-gated and follow it with:

```markdown
> **Amended 2026-08-22** (`2026-08-22-igdb-auto-fallback-design.md` §4): this still holds for `igdb_import` and `company_create`, but **not** for the game path. `DeclareGameView.post` now accepts an `igdb` id and imports it for an anonymous visitor. The reasoning is in that spec: the write is one games-catalogue row from IGDB's own data, through the idempotent upsert, bounded by a per-IP quota — no user data, and the credit still cannot be published before email verification.
```

- [ ] **Step 4: Record the setting in `docs/03-TECH-STACK.md`**

Add `IGDB_RATELIMIT` to the environment-variable listing next to `SEARCH_RATELIMIT`, described as "live IGDB fallback quota per IP; over quota means no call, never an error".

- [ ] **Step 5: Add the ROADMAP entry**

Under "Post-roadmap additions", extend the existing **IGDB live fallback** entry with:

```markdown
**Superseded 2026-08-22**: the fallback is no longer a deliberate click. A search returning zero local rows queries IGDB automatically, on the credit form (`hx-trigger="load"`, no new JS) and in the anonymous funnel (server-rendered). Protection is a 24 h cache on the normalised query — misses cached too, since repeated misses are the traffic worth suppressing — plus `IGDB_RATELIMIT` (10/m per IP), which **skips the call instead of 403-ing the page**, and which a cache hit never spends. Search timeout 10s → 4s, since it now runs inside a page render. Spec: `docs/superpowers/specs/2026-08-22-igdb-auto-fallback-design.md`.
```

- [ ] **Step 6: Run the full toolchain and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check
git add docs/ ROADMAP.md
git commit -s -m "docs: record the automatic IGDB fallback and the rule it amends

docs/01 §3.1 (automatic on a local miss, cache and quota, degradation),
§3.3 and the 2026-08-11 funnel spec (the anonymous game-import path, and
what stays login-gated), docs/03 and ROADMAP."
```

- [ ] **Step 7: Open the PR**

```bash
git push -u origin feat/igdb-auto-fallback
gh pr create --base main --title "Automatic IGDB fallback on a catalogue miss" --body "Implements docs/superpowers/specs/2026-08-22-igdb-auto-fallback-design.md. Highlight for review: the amended login-gate rule in Task 6 (contributions/views.py), and the quota that skips rather than blocks (games/igdb.py)."
```

---

## Self-review

**Spec coverage.** §1 `cached_search`, normalisation, cached misses, 4 s timeout, `igdb_label` move → Task 1. §2 setting, `.env.example`, never-blocks, cache-hit-costs-nothing → Tasks 2-3. §3 auto-fetch on a miss, manual click when matches exist, `throttled` branch → Tasks 3-4. §4 funnel GET, funnel POST, the amendment → Tasks 5-7. §5 copy — `Searching IGDB…` (T4), `Not in our catalogue yet` (T5), `IGDB search is busy right now…` (T3), `That game is no longer listed on IGDB.` (T5) — all present, all through i18n. §6 out of scope: no IGDB company search anywhere in this plan. §7 all eleven listed tests map to a task.

**Placeholders.** None. Every code step carries its code, every command its expected output.

**Type consistency.** `search_options(request, query, client=None) -> list[dict[str, Any]] | None` is defined in Task 3 and consumed unchanged in Task 5. `quota_exceeded(request) -> bool` is defined in Task 2 and consumed in Tasks 3 and 6. `igdb_label(result) -> str` is defined in Task 1 and consumed in Task 3's `search_options`. `cached_search(query, limit=10, client=None)` is defined in Task 1 and consumed in Task 3. The `igdb_error` attribute is declared in Task 5 and set in Task 6.

**One refinement over the spec, stated so it is not mistaken for drift.** The spec names `cached_search(query, limit)` and describes the quota check separately. The plan keeps `cached_search` exactly as specified and adds `search_options` on top, because the spec's own invariant — *a cache hit must not spend quota* — is otherwise a rule every caller has to remember. Folding cache, quota and labelling into the one function both callers need makes it structural instead.

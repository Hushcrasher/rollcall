# The home page becomes the people search — design

> Status: validated 2026-08-11. Behavior source of truth stays
> [docs/01-DESIGN.md](../../01-DESIGN.md); this spec changes where the people
> search lives and retires two pages. No model change, no migration.

## Problem

`/` is a menu. It carries one sentence and four links — search, your profile,
add a credit, for recruiters — and every one of them is reachable from the nav
bar or one click deeper. It costs the visitor a click and returns nothing for
it: no data, no tool, no decision made.

The tool that *should* be there already exists at `/search/recruiters/`: the
people search, open to everyone since 2026-07-16. It is currently two clicks
from the root and named after an audience rather than a job.

Two smaller frictions fall out of the same area:

- The nav search box is labelled `Search…`. It matches games, companies **and**
  people, and says none of that.
- `/search/for-recruiters/` is a promise page whose only real job is proving to
  *workers* that the recruiter side exists (docs/01-DESIGN.md §3.6). Once the
  search itself is the home page, the tool is its own proof.

## Scope

Serve the people search at `/`. Delete the landing page and the "For recruiters"
promise page, and their nav/footer links. Keep the pitch alive for anonymous
visitors as a line above the form. Fix the nav placeholder.

Out of scope: the search itself — filters, query, result cards, pagination and
`recruiter_search()` are untouched. The recruiter application flow is untouched
too; it simply loses its last inbound link (see *Dormant flow* below).

## Routes

| Route | Name | View | Status |
|---|---|---|---|
| `/` | `home` | `PeopleSearchView` | was a `TemplateView` on `home.html` |
| `/search/recruiters/` | — | — | **deleted** → 404 |
| `/search/for-recruiters/` | — | — | **deleted** → 404 |
| `/search/?q=` | `search:search` | `SearchView` | unchanged — the nav box's results page |
| `/search/suggest/` | `search:suggest` | `suggest` | unchanged — the nav typeahead |
| `/search/filters/{engines,genres,countries}/` | unchanged | | unchanged — the form's own htmx typeahead |
| `/search/games/`, `/search/companies/` | unchanged | | unchanged — the credit form's autocomplete |

The URL **name stays `home`**. That is the point of putting the view there
rather than redirecting: `{% url 'home' %}` in the logo and everywhere else
keeps resolving, and the root genuinely *is* the page instead of bouncing to
another address.

`search:recruiter_search` disappears as a name. Its three call sites become
`home`: `accounts/views.py` (approved recruiter → the search),
`search/tests/test_recruiter_search_view.py`, `search/tests/test_filter_autocomplete.py`.

Both deletions are 404s rather than redirects. `/search/recruiters/` is
`Disallow`ed today, so nothing indexed points at it; `/search/for-recruiters/`
is `Allow`ed but the site is not deployed, so no external link exists yet. There
is nothing to preserve, and a redirect would only leave a route to maintain.

### Renames

- `search.views.RecruiterSearchView` → `PeopleSearchView`
- `templates/search/recruiter_search.html` → `templates/search/people_search.html`
- deleted: `search.views.RecruitersLandingView`,
  `templates/search/recruiters_landing.html`, `templates/home.html`

The view keeps living in the `search` app; only its URL moves. `config/urls.py`
imports it for the root route, the way it already imports `robots_txt` from
`config.sitemaps`.

## The root page

The `<h1>` stays **"Find people by what they've worked on"**. It names the job
rather than the audience, which is what the page now is for everyone.

Above the form, **for anonymous visitors only**:

> Rollcall is a credits database for the video game industry. Declare your work,
> be found by recruiters for what you actually shipped.
> — *Create your account*

This is `home.html`'s existing copy, moved verbatim, with the signup link that
was already there. It is not new marketing: it is the only surviving statement
of the recruiter promise now that `/search/for-recruiters/` is gone, and
docs/01-DESIGN.md §3.6 makes that promise load-bearing for worker motivation —
"candidate motivation depends on believing the recruiter side exists".

Logged-in members see the form alone. They have an account; the pitch is spent.

The rest of the template — the typeahead scratch form, the chips script, the
`noscript` note, the result cards, the pagination — moves across unchanged.

## Rate limiting

Today `RecruiterSearchView.get` carries a class-level
`@ratelimit(key="ip", rate=SEARCH_RATELIMIT, block=True)`. At `/` that would
mean every anonymous hit on the **home page** spends quota: crawlers, link
previews, health checks, and every colleague behind one office NAT. A 403 on a
search page is an annoyance; a 403 on the home page is the site being down. The
counter also lives in the per-process in-memory cache (a known follow-up in
ROADMAP.md), so the behavior is already uneven across workers.

The decorator is replaced by a conditional check inside `get()`: quota is spent
only when `request.GET` is non-empty.

- A bare `/` always answers.
- Any URL carrying a query string is rate-limited — which is exactly the
  combinatorial filter surface worth protecting, and exactly the crawl-trap
  surface robots.txt targets below.

`?page=2` and junk params count as searches. That is deliberate: they are part
of the same generated URL space, and treating them as free would leave the
cheapest enumeration path unmetered.

The rate-limit group is named explicitly (`"people_search"`) so it stays a
separate counter from `SearchView`'s, which is the behavior today — django-
ratelimit derives the group from the view's module and name, so the rename would
otherwise silently move the counter.

Protection level is unchanged from today for real searches. The mitigations
listed in docs/01-DESIGN.md §3.6 — IP rate limit, pagination, `profile_public` —
all still hold, and the form's ≥1-filter rule remains a UX guard, **not** an
anti-enumeration boundary.

## robots.txt

`Allow: /search/for-recruiters/` is removed with the page. `/search/` stays
disallowed as a whole, which still covers `/search/?q=`, `/search/suggest/` and
the htmx filter endpoints.

The new problem is that the crawl trap moved to the root. It cannot be closed
with a path prefix: `Disallow: /` would delist the entire site. So it is closed
by query string instead — `Disallow: /*?` joins `_DISALLOW`:

- `/` itself carries no query string and stays crawlable, as a home page must.
- `/?discipline=3&engines=5&page=2` and every sibling are excluded.
- `/u/`, `/g/` and `/c/` are clean-path URLs, so nothing indexable is lost. The
  one query-string URL under them is `/u/<slug>/?preview=member`, which is
  owner-only and renders the same content anyway.

**Coverage is partial, and the file must say so.** RFC 9309 §2.2.3 defines `*`
in a path, and Google and Bing implement it — but Python's own
`urllib.robotparser` ignores wildcards and will read `/*?` as a literal prefix
matching nothing. The trap is therefore closed for the crawlers that would
actually burn budget on it, and open to naive parsers. This is the same kind of
caveat the file already documents for first-match versus longest-match
semantics, and it is recorded next to it rather than glossed over.

Ordering is unchanged: `_ALLOW` is still emitted before `_DISALLOW`. No `Allow`
entry matches a root query-string URL, so `/*?` applies under both first-match
and longest-match parsers.

As a second layer, the root template gets `<link rel="canonical">` pointing at
`/`. robots.txt stops the crawl; the canonical collapses any filtered variant
that is reached anyway — a disallowed URL can still be indexed from an external
link, and filtered result pages are not distinct content.

## Navigation

- **Placeholder**: `Search…` → **"Search games, companies and people"**. The
  box already matches all three (`suggest()` returns games, people and
  companies); the label just stops under-selling it.
- The input has no declared width, so it falls to the browser default of roughly
  20 characters and would truncate that placeholder. It gets `size="34"` — one
  more than the 33-character string — so the label is fully visible. Without it
  the fix is invisible, which is the whole failure it is meant to correct.
- **Footer**: the "For recruiters" link goes. Terms, Privacy and Report remain.
- **Logo**: already `{% url 'home' %}`. Unchanged, and now lands on the search.

The consequences the change accepts, stated plainly: the only route to one's own
profile is "My profile" in the nav, and the only route to game/company/person
lookup is the nav search box. Both are present on every page for a logged-in
member, so neither is lost — but neither has a second entry point any more, and
"Add a credit" now sits one click deeper, on the profile page.

## Dormant flow

`accounts:recruiter_apply` loses its only inbound link when the promise page is
deleted. The route, view, form, template and admin approval action all stay
working and tested. This matches its documented status in docs/01-DESIGN.md
§3.6 — "stays in place and working, but no longer gates anything… kept cheap to
re-arm if paid recruiter accounts return". Unlinked is what dormant looks like;
re-arming means adding a link back, not rebuilding the flow.

## Testing

| Module | Change |
|---|---|
| `games/tests/test_home.py` | rewritten: `/` returns 200, renders the search form, shows the signup CTA to an anonymous visitor and not to a logged-in one |
| new: rate-limit coverage | bare `/` is never limited; `/` with a query string is |
| `search/tests/test_recruiters_landing.py` | deleted with the page |
| `search/tests/test_recruiter_search_view.py` | `reverse("search:recruiter_search")` → `reverse("home")` |
| `search/tests/test_filter_autocomplete.py` | same reverse update |
| `games/tests/test_seo.py` | drops the `Allow: /search/for-recruiters/` assertion, gains `Disallow: /*?` |

The rate-limit tests need the limiter enabled, which is disabled globally in the
test settings — they follow the existing focused-403 pattern in
`test_recruiter_search_view.py` rather than inventing a new one.

Every existing people-search test keeps passing untouched apart from the URL it
reverses. That is the check that this change is routing and presentation only:
if a filter or result-card test needs editing, something moved that shouldn't
have. Expected count: 367 today → roughly 366–368.

## Docs to update

- **docs/01-DESIGN.md §3.6** — the bullet describing the public "For recruiters"
  page as a validated decision now describes a page that does not exist. It is
  rewritten to say the search itself is the promise, at the root, with the pitch
  line carrying it for anonymous visitors. The robots.txt sentence in the same
  bullet is updated to the query-string rule.
- **ROADMAP.md** — an entry under *Post-roadmap additions*.

## Not doing

- No redirect from the two deleted URLs (nothing points at them; see *Routes*).
- No change to the search query, filters, ordering or result cards.
- No change to `/search/?q=`, the nav typeahead, or their endpoints.
- No new model field and no migration.
- Redis for the rate-limit counter stays a known follow-up. Making the bare root
  free of quota reduces the blast radius of the in-memory cache but does not
  replace that fix.

# Open Graph cards — design

> Status: proposed 2026-08-21; the four design forks below were validated with
> the product owner the same day, the spec itself is under review in its PR.
> Behavior source of truth stays [docs/01-DESIGN.md](../../01-DESIGN.md). Adds
> one small app (`cards`), three image endpoints, meta tags in `base.html`, and
> an owner-only share row on the profile page. No model change, no migration.

## Problem

A Rollcall link pasted on LinkedIn, Bluesky, X, Discord or Slack renders as a
bare URL: the site emits **no** `og:*` / `twitter:*` meta tags, nowhere. The
product's cheapest acquisition loop — a worker shares their profile, a
recruiter or a colleague clicks — has no hook: nothing previews, nothing
invites the share.

The data a card needs already exists: `search/services.py` computes per-person
summaries (`credits_count`, `games_count`, `first_year`, `last_year`) for the
result cards, the profile page has the person's latest credit, and game pages
have the credited people.

## Decisions (validated 2026-08-21)

| Question | Decision |
|---|---|
| Scope | **Profiles + game pages + a site-wide default card** |
| Image | **Server-rendered PNG, text only**, cached — no illustration, one vendored open font |
| Profile card content | **Display name · latest job title · stats line · location · "Open to work"** |
| Share nudge | **Owner-only share row** on the profile: copy link, LinkedIn / Bluesky / X, preview |

## 1. Meta tags (`templates/base.html`)

A `{% block meta %}` in `<head>` renders, for every page:

```html
<meta name="description" content="{{ meta_description }}">
<meta property="og:site_name" content="Rollcall">
<meta property="og:type" content="{{ og_type|default:'website' }}">
<meta property="og:title" content="{{ og_title }}">
<meta property="og:description" content="{{ meta_description }}">
<meta property="og:url" content="{{ og_url }}">
<meta property="og:image" content="{{ og_image }}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
```

- Defaults come from a context processor `cards.context_processors.og_defaults`:
  `og_title` = "Rollcall", `meta_description` = "Find people by what they've
  worked on — a public credits register for the game industry.", `og_url` =
  `request.build_absolute_uri()` (the house pattern; `accounts/emails.py`,
  `config/sitemaps.py`), `og_image` = absolute URL of the default card.
- `accounts/profile.html` and `games/game_detail.html` override the four values
  through their views' context: profile → title `"{display_name} · Rollcall"`,
  description = the stats line, `og_type` `profile`, image = the profile card
  URL; game → title `"{title} ({year}) · Rollcall"`, description = "N people
  credited on Rollcall", image = the game card URL.
- **Privacy**: a non-public profile 404s for everyone but its owner (existing
  `_visible_users` rule), so crawlers never see its tags. The owner's own view
  of a private profile still renders the tags — harmless, the image endpoint
  refuses to serve it (§2). No tag ever carries an email or any non-`active`
  credit (`search/services.py` summaries are already `active`-only).

## 2. Card images — a new `cards` app

Cross-cutting (profiles, games, default) with its own asset (fonts) and its own
tests: a small app rather than a module bolted onto `accounts`.

```
cards/
  apps.py, urls.py, views.py
  context_processors.py     og_defaults
  data.py                   profile_card(user) / game_card(game) / default_card() → CardData
  render.py                 render(CardData) → bytes   (pure: no DB, no request)
  fonts/Inter-Regular.ttf, fonts/Inter-Bold.ttf, fonts/OFL.txt
  tests/
```

### Routes

| Route | Name | Serves |
|---|---|---|
| `/u/<slug>/card.png` | `cards:profile` | the person's card — **404 unless `profile_public=True`** |
| `/g/<slug>/card.png` | `cards:game` | the game's card |
| `/card.png` | `cards:default` | the site card |

Every URL the meta tags emit carries `?v=<token>`: `token` is a short hash of
the `CardData` (name, job title, stats…), so a profile that changes gets a
**new image URL** and the networks — which cache `og:image` for days — fetch a
fresh one. The view ignores the value of `v` except as part of its cache key.

### `CardData` (what a card may show — and nothing else)

```
CardData(kind: "profile" | "game" | "default",
         title: str,                 # display name / game title / "ROLLCALL"
         subtitle: str = "",         # latest job title / "Released 2021"
         stats: str = "",            # "6 credits · 5 games · 2016–present" / "14 people credited on Rollcall"
         footer: str = "",           # "Lyon · France" / "" / "Find people by what they've worked on"
         badge: str = "")            # "Open to work" or ""
```

- **Profile**: `title` = `display_name`; `subtitle` = `job_title` of the most
  recent `active` credit (latest `start_date`); `stats` from the same query the
  search cards use — reuse by extracting the per-user aggregate of
  `search/services.py::_assemble_results` into a `profile_summary(user)`
  helper in `search/services.py` (search logic stays there; `cards/data.py`
  only calls it); `footer` = `location_display`; `badge` = "Open to work" when
  `open_to_work`. Empty fields are omitted, the layout collapses upward.
- **Game**: `title`, `subtitle` = "Released {year}" when `release_date`,
  `stats` = "{n} people credited on Rollcall" counting distinct users with an
  `active` credit **and** `profile_public=True` (the same people the page
  lists; n = 0 → "Be the first to claim a credit").
- **Default**: `title` "ROLLCALL", `footer` the site tagline.
- Every string goes through `gettext`; the card renders in the request's
  language like any page (English today).

### Rendering (`render.py`, Pillow)

1200×630, white `#FFFFFF` background. **Text only**, no shapes but the text,
no avatar, no icons (the "+ avatar" variant was considered and rejected — it
adds image composition for little gain and can wait). Type: **Inter** (SIL OFL
1.1, vendored with its licence; Pillow ships no usable font) for every element
but the wordmark, amended below:

| Element | Face | Size | Colour |
|---|---|---|---|
| Wordmark `ROLL` / `CALL`, top-left, two lines | JetBrains Mono Bold | 36 px | `#0172AD` (Pico's primary, the same blue as the site) |
| `title` | Bold | 72 px, shrinks to 56 then 44 to fit one line, then ellipsis | `#111111` |
| `subtitle` | Regular | 40 px, one line, ellipsis | `#111111` |
| `stats` | Regular | 36 px | `#555555` |
| `footer` | Regular | 32 px | `#555555` |
| `badge` | Bold | 32 px, plain text, right of the footer | `#0172AD` |

> **Amended 2026-08-21 by spec `2026-08-21-search-chrome-design.md` §1**
> (product owner decision). The wordmark was one line, `ROLLCALL` in Inter
> Bold; it is now two lines, `ROLL` over `CALL`, in **JetBrains Mono Bold**
> (SIL OFL 1.1, vendored as `cards/fonts/JetBrainsMono-Bold.ttf` with its own
> licence file) — monospace makes the two four-glyph lines the same width by
> construction, echoing the stacked wordmark the same spec puts in the nav.
> Size and colour are unchanged; every other element still renders in Inter.

60 px side margins, 24 px vertical rhythm; the text block is **vertically
centred** in the card (networks crop edges, and a top-aligned block leaves the
lower half empty — validated on rendered samples, 2026-08-21). No radius, no
shadow, no gradient — the
card is the site's typographic voice, not a poster. (These values are the
reviewable design; change them here, not in code comments.)

**Non-Latin names.** Inter covers Latin, Greek and Cyrillic, not CJK, Arabic,
Devanagari… Rendering those with Inter prints `.notdef` boxes — worse than
nothing for a Japanese developer sharing their profile. v1 rule: if any
character of `title`/`subtitle`/`footer` falls outside Inter's coverage
(checked against a conservative set of Unicode blocks), the card renders the
**default layout with the site tagline** instead of the text, and the profile
tags still point at it (a neutral card beats a broken one). A vendored Noto
fallback chain is the documented v2; the check and its test make the
limitation explicit rather than silent.

### Serving, caching, limits

- `cache.get_or_set(f"card:{kind}:{slug}:{token}", render, timeout=3600)`
  (Redis in prod, locmem in dev). Response: `image/png`, `Cache-Control:
  public, max-age=3600`, `X-Content-Type-Options: nosniff`.
- Rate limit: `key="ip"`, rate `PROFILE_RATELIMIT` (120/m), named group
  `"card"` — a render is ~20–50 ms of CPU; the cache makes repeats free, the
  limit bounds a cold-cache flood the same way profile pages are bounded.
- Security posture: cards take **no user-uploaded bytes** (the avatar is out);
  every string is drawn as text by Pillow, never interpreted; fonts are
  vendored, trusted assets; the only inputs are a slug and a cache token.

## 3. Share row (`accounts/profile.html`, owner only)

Under the owner's `Edit my profile · View as member` links:

```
Share your profile:  [Copy link]  LinkedIn · Bluesky · X · Preview your card
```

- `Copy link`: a `<button>` with three lines of inline JS (`navigator.clipboard
  .writeText`, then swaps its label to "Copied" for two seconds); without JS
  the absolute profile URL is shown as selectable text next to it.
- Network links are plain `<a target="_blank" rel="noopener">` to the
  networks' share intents with the encoded profile URL (LinkedIn
  `sharing/share-offsite/?url=`, Bluesky `bsky.app/intent/compose?text=`, X
  `twitter.com/intent/tweet?url=&text=`). No SDKs, no tracking scripts.
- `Preview your card` opens `cards:profile` for the owner.
- A private profile shows instead: "Your profile is private — make it public
  to share it." linking to profile edit. The row never renders for visitors.
- Every string through i18n; layout from Pico; nothing added to `app.css`
  beyond, if needed, an inline-flex rule for the row (functional).

## Out of scope

Avatar on the card; dark-mode variant; localized cards; company cards; a Noto
fallback font chain (v2); og:video; per-discipline art.

## Docs & tests

- `docs/01-DESIGN.md`: profile §(share row, card), SEO §(meta tags);
  `docs/03-TECH-STACK.md`: Inter (OFL) vendored for cards; `ROADMAP.md` entry.
  `docs/02-ARCHITECTURE.md` §apps: the `cards` app.
- Tests (house TDD):
  - meta tags present on home / profile / game with **absolute** `og:url` and
    `og:image`; `og:image` carries `?v=`; the token changes when a credit is
    added; no tag contains an `@`.
  - private profile: card endpoint 404s; the page 404s for a visitor (existing).
  - card endpoint: 200, `image/png`, decodes to 1200×630; cached on the second
    call (render spied once); rate-limited.
  - `profile_card()` / `game_card()` data mapping: latest job title, stats
    string, `open_to_work` badge, location; `n` counts public users only.
  - `render()` pure tests: default card; long title shrinks then ellipsizes
    (assert via the chosen size, not pixels); non-Latin falls back to the
    default layout.
  - share row: owner sees it, visitor doesn't, private owner sees the notice.

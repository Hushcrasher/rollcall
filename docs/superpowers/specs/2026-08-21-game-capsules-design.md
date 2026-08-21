# Game capsules on game pages and credit lines — design

> Status: proposed 2026-08-21, decision validated with the product owner the
> same day. No model change: `Game.cover_url` already exists (the seed fills
> it from the Steam `header_image`, the IGDB import from the IGDB cover) and
> the game page already renders it. Dev fixtures carry none, which is why the
> pages look bare locally.

## Decision

When `cover_url` is empty and the game has a `steam_appid`, **derive the
capsule from Steam's public CDN**; otherwise show nothing. No mirroring, no
API call, no storage.

## 1. `Game.capsule_url` (property, `games/models.py`)

```
STEAM_CAPSULE_URL = "https://shared.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"

@property
def capsule_url(self) -> str:
    if self.cover_url:
        return self.cover_url
    if self.steam_appid:
        return STEAM_CAPSULE_URL.format(appid=self.steam_appid)
    return ""
```

One constant, so a CDN move is a one-line change (measured 2026-08-21: the
`cloudflare.`-prefixed hosts answer an uncached 301 to this host; a real app
id serves `image/jpeg` with a 10-year cache; an unknown id 404s). The
460×215 "header" asset is the capsule used on the store and is the only
size we need — CSS scales it.

## 2. Rendering

- **Game page** (`games/game_detail.html`): the existing cover `<img>` switches
  to `capsule_url`, `alt=""` (decorative — the title is the text), and
  `onerror="this.remove()"` so a dead CDN URL leaves no broken-image icon —
  not lazy, it is the page's largest above-the-fold element. Width capped by
  one functional rule (`.capsule { max-width: 460px; height: auto; }`).
- **Profile credit lines** (`accounts/profile.html`) and the game lists on
  company pages: a small capsule thumbnail (`.capsule-sm`, 92×43 — the store's
  small capsule ratio, scaled by CSS) to the left of the line, same
  `onerror` guard; no thumbnail when `capsule_url` is empty, the line keeps
  its current shape.
- OG cards: untouched (text only by decision).
- Referrer: `<img referrerpolicy="no-referrer">` on the Steam-derived URLs,
  so the capsule requests don't announce member profile URLs to a third party.

## 3. Posture

Hot-linking Steam's public store assets is what the store pages themselves
do; it is Steam-derived use, which the owner accepted knowingly on
2026-08-21 (see the public-release decisions). No image bytes ever pass
through Rollcall — the `accounts/images.py` pipeline is not involved — so no
new upload/decode surface opens.

## Out of scope

Mirroring capsules to R2; IGDB cover fetches at request time; capsules in
search result cards (many images per page — revisit with measurements).

## Docs & tests

`docs/01-DESIGN.md` (game page + credit lines), ROADMAP. Tests: `capsule_url`
prefers `cover_url`, derives from `steam_appid`, is empty otherwise; game page
renders the derived URL with `referrerpolicy` and `onerror`; profile credit
line shows the thumbnail only when a URL exists.

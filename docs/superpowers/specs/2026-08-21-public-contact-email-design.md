# Optional public contact email — design

> Status: proposed 2026-08-21, decision validated with the product owner the
> same day. **This amends non-negotiable #1** of `docs/00-README.md` and the
> first hard rule of `CLAUDE.md`. One model field (`User.public_email`, one
> migration), settings UI, profile display, policy docs, and the tests that pin
> the old rule.

## Problem

Members may *want* to be reachable directly — LinkedIn lets them publish an
address — and today the only channel is the relay. The rule that protects
people ("your email is never shown") should not stop the ones who choose to
publish one.

## Decision

A **separate, opt-in `public_email`** field. The **account email stays
private forever**; a contact address the member types in deliberately is
shown on their public profile, and nowhere else.

The rule becomes:

> The account email is never displayed or exposed anywhere. A member may
> publish a *separate* contact address on their profile; it appears only on
> the public profile page, never in cards, feeds, search results, exports to
> third parties, or logs.

## 1. Model (`accounts/models.py`, migration)

`public_email = models.EmailField(_("public contact email"), blank=True,
default="")` — stored lowercased like every email write path
(`SignupForm.clean_email` precedent), **no** uniqueness (two members may share
a studio address), independent from `email`. A member may type the same
address as their account email — that is allowed: what the rule protects is
that the *login* field is never read for display; only the field they chose to
publish is.

## 2. Settings (`profile_edit.html`, `ProfileForm`)

Field under `contactable`, label `Public contact email (optional)`, help:
`Shown on your public profile to anyone. Leave empty to be reachable only
through Rollcall messages.` Lowercased in `clean_public_email`.

## 3. Profile (`accounts/profile.html`)

For visitors of a **public** profile with a non-empty `public_email`:
`<a href="mailto:…">address</a>` under the location line; the relay button
keeps its existing place on the page (its `Message` label lands with spec
2026-08-21-search-chrome). The owner sees the same block plus a muted
`Shown publicly` note. Private profile → the page 404s already.

## 4. Where it must NOT appear — and the tests that prove it

- OG cards and meta tags: `CardData` fields unchanged; the meta "no `@`"
  sweep (`cards/tests/test_meta.py`) stays green **as is** — the new field
  never reaches the tags.
- Home feed, search result cards, the contact relay's mails (which still
  Reply-To the relay), sitemaps, game pages.
- JSON export: the member's own export includes it (it is their data).
- Logs: nothing new is logged.
- The existing "never leaks a contributor email" tests (`games/tests/test_pages.py`,
  `accounts/tests/test_profile.py`…) keep asserting the **account** email is
  absent; new tests assert `public_email` shows on the public profile, not on
  the game page, not in the feed, not in a card, and not on a private profile.

## 5. Policy documents

- `docs/00-README.md` #1 and `CLAUDE.md` first hard rule: reworded as above.
- `docs/01-DESIGN.md` §3.4 (profile fields), privacy policy template: add the
  sentence that a published contact address is visible to anyone and can be
  removed at any time from settings; `docs/04` §1 (new column).
- About page "Contact and safety" paragraph: "Personal email addresses are
  never shown unless a member chooses to publish a contact address."

## Out of scope

Email verification of the public address; obfuscation/anti-scraping of the
displayed address (it is the member's explicit choice); a "show email to
recruiters only" tier.

## Tests

Lowercasing; display on public profile to anonymous and logged-in visitors;
absence everywhere listed in §4; export includes it; the policy texts contain
the new wording.

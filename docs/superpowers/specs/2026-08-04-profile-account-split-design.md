# Profile / Account split — design

> Status: validated 2026-08-04. Behavior source of truth stays
> [docs/01-DESIGN.md](../../01-DESIGN.md); this spec refines where the existing
> fields live, and adds no new field.

## Problem

"Settings" and "My profile" are not clearly distinct. `/settings/` currently
hosts a form of eight profile fields (display name, bio, city, country, avatar,
the three visibility booleans) plus a GitHub URL — all of them descriptions of
the person, not of the account. Meanwhile "My profile" in the nav points at
`/u/<slug>/`, the public page, which is where a member would expect to edit
those fields.

A second, quieter problem falls out of the same area. `profile_public` defaults
to `True` and can be turned off in that form. Turning it off makes the member
invisible everywhere — 404 for visitors, excluded from the people search,
excluded from the sitemap — but `_visible_users` deliberately exempts the owner
([accounts/views.py:60](../../../accounts/views.py)), so the member keeps seeing
their own profile exactly as before. Nothing on screen says they are invisible.
A member can add credits for months while unreachable, with no signal.

## Scope

Move the eight profile fields plus `github_url` out of the account page and onto
a dedicated profile-edit page. Reduce the account page to email verification,
data export and account deletion, and rename it "Account". Add a "View as
member" preview to the profile page, and a neutral private-profile notice.

No model change and **no migration**: only routing, view/form placement and
templates move.

## Routes

| Route | Name | View | Status |
|---|---|---|---|
| `/profile/` | `accounts:my_profile` | `my_profile_redirect` | new — redirects to `/u/<own-slug>/` |
| `/profile/edit/` | `accounts:profile_edit` | `ProfileEditView` | new — the moved form |
| `/u/<slug>/` | `accounts:profile` | `ProfileView` | existing, gains preview + private notice |
| `/account/` | `accounts:account` | `AccountView` | renamed from `accounts:settings` |
| `/account/delete/` | `accounts:account_delete` | `AccountDeleteView` | path renamed |
| `/account/export/` | `accounts:export_data` | `export_personal_data` | path renamed |

`accounts:settings` disappears as a name, so every `reverse` of it is updated
mechanically — including the two out-of-scope redirects noted below, whose
*destination* is not revisited even though their *reference* must change.

The edit route carries **no slug**. The object edited is always `request.user`,
so a slug in the URL would carry no information and would need a 404 branch for
`/u/someone-else/edit/`. Without it the mismatch cannot be expressed.

`/profile/` exists because `LOGIN_REDIRECT_URL` is a plain string setting and
cannot pass a `slug` to `reverse()`; it cannot point at `accounts:profile`
directly. The redirect view resolves the slug at request time, and doubles as
the nav's stable "My profile" target.

URL renames are safe here: the POC has no inbound links to `/settings/`, and
`/settings/` is `Disallow`ed from crawlers today, so no indexed URL breaks.

## Form and views

`SettingsForm` is renamed **`ProfileForm`**, unchanged otherwise — same eight
model fields, same `github_url` handling (parse, and drop the GitHub cache when
the login changes).

`ProfileEditView` is a `LoginRequiredMixin` + `UpdateView` whose `get_object`
returns `request.user`. Its template keeps `enctype="multipart/form-data"` for
the avatar. On success it redirects to `self.object.get_absolute_url()` — the
member lands on their profile and sees the result — with the message
"Your profile was saved."

`SettingsView` becomes `AccountView`, a plain `TemplateView` with no form. It
keeps exactly three things:

- the "Your email is not verified yet — verify it to add credits" warning and
  its "Resend the link" action, shown only when unverified;
- "Download my data (JSON)";
- "Delete my account".

## The three views of a profile page

`ProfileView.get_context_data` computes:

```python
is_self = request.user.is_authenticated and request.user.pk == self.object.pk
preview = is_self and request.GET.get("preview") == "member"
context["is_owner"] = is_self and not preview
context["preview"] = preview
context["private_notice"] = is_self and not self.object.profile_public
```

`?preview=member` is honored only for the owner. For anyone else it is a no-op —
they already see the member view — so the parameter can never change what a
third party sees.

**Owner** (`is_owner`): "Edit my profile" button, "Add a credit", Edit/Delete on
each credit, and a "View as member" link to `?preview=member`.

**Preview**: every owner control disappears. A bar at the top reads
"Preview — what a logged-in member sees" with a "Back to my profile" link. The
Contact and Report affordances render according to `contactable`, but **inert**
(`<span>`, not `<a>`): clicking Contact on your own profile would hit the
relay's self-contact refusal, a dead end that teaches nothing.

**Member / anonymous**: unchanged. The preview link is rendered only for the
owner, so crawlers never encounter `?preview=member` and no `nofollow` or
`noindex` is needed.

### Private-profile notice

When `private_notice` is true, the profile page shows, above the profile:

> Your profile is private: nobody else can see this page, and you don't appear
> in any search. — *Change this*

It shows in both the owner view and the preview. In preview we deliberately do
**not** simulate the visitor's 404: rendering the page with this notice answers
the member's actual question, where a 404 would only reproduce a symptom.

The wording is a statement of fact with a quiet link, not a prompt. This flag is
documented as a safety valve, and members who set it deliberately — to stay
hidden from a harasser or a current employer — must not be nagged about a
protective choice. The notice confirms their setting works; it does not push
them to reverse it.

## Navigation and redirects

- The "Rollcall" logo points to the home page instead of the account page.
- Nav: "My profile" → `accounts:my_profile`; "Settings" → "Account".
- `LOGIN_REDIRECT_URL` → `accounts:my_profile`.
- `verify_email` on success redirects to the member's profile: the message says
  they can now add credits, and the profile is where that happens.
- `robots.txt` `_DISALLOW`: `/settings/` → `/account/`, plus `/profile/`, which
  by prefix also covers `/profile/edit/`.

Two redirects to the account page are **out of scope and deliberately left
alone**: `ReportView.success_url` ([contact/views.py:90](../../../contact/views.py))
lands on it after a report, and `RecruiterApplyView` does the same in a dormant
flow. Both are odd, neither belongs to this change.

## Testing

Existing tests move with the code:

- `test_settings.py` → the six field-update tests become `test_profile_edit.py`,
  aimed at `/profile/edit/`. What stays behind, as `test_account.py`, asserts
  the thin page: verification warning when unverified, export link, delete
  link, and **no form** on the page.
- `test_github_settings.py` follows the `ProfileForm` rename.

New — `test_profile_preview.py`:

- preview hides every owner control;
- preview renders Contact inert, and only when `contactable`;
- a private profile shows the notice to its owner, in both plain and preview
  views;
- `?preview=member` on someone else's profile changes nothing;
- `/profile/edit/` requires login;
- `/profile/` redirects a logged-in member to their own slug.

Unchanged and expected to stay green: the profile visibility tests
(`test_profile.py`), which pin the 404 for private profiles and the "email never
rendered" rule.

## Deliberately not in this change

Previewing the **search result card** — the rich card a recruiter actually meets
first (matched credits, career stats, engine shares) is a different surface from
the profile page, and "View as member" does not preview it. Worth knowing when
reading the button's promise; not worth building now.

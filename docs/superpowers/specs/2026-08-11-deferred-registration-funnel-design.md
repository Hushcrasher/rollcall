# Deferred registration — the credit comes first, the account last

> Status: validated 2026-08-11. Behavior source of truth stays
> [docs/01-DESIGN.md](../../01-DESIGN.md). Builds on
> [2026-08-11-home-is-people-search-design.md](2026-08-11-home-is-people-search-design.md),
> which made `/` the people search.

## Problem

Success metric #1 is that industry people, not individually solicited, create an
account and declare at least one complete contribution. Today the only path to
that is: understand what Rollcall is → decide to sign up → create an account →
verify an email → find the credit form → fill it. The account is demanded before
any value is delivered, and every step before the credit is pure cost to the
visitor.

The site now asks nothing of an arriving worker. The root serves the people
search — a tool aimed at the other side of the market — and the only thing
addressed to a worker is one sentence of pitch with a signup link.

Meanwhile the one question this audience actually wants to answer is cheap to
ask: *which game did you work on?* It is not a form field, it is an identity
question, and someone who shipped a title is usually glad to name it.

## Scope

Ask the question first. A visitor fills a complete credit — game, discipline,
job title, optional employer, dates — and only then creates an account. The
credit is preserved across signup and published when the email is verified.

**Out of scope, deliberately:** the referral loop (letting a member name
colleagues they worked with, so Rollcall can invite them). It was discussed at
length on 2026-08-11 and deferred to its own spec — see *Deferred* below. This
spec adds no way for anyone to record anything about another person.

## The flow and where state lives

| Step | Route | Where the data lives |
|---|---|---|
| 1. "Which game did you work on?" | `/` (field only), submits to `/declare/` | session |
| 2. The rest of the credit | `/declare/details/` | session |
| 3. Create the account | `/declare/account/` | session |
| 4. Account created, auto-login, verification email sent | — | **DB row, `status='pending'`** |
| 5. Email verified | `/verify/<uidb64>/<token>/` | `status` flips to `active` — published |

The session carries steps 1→3 only: one continuous sequence, same tab, minutes
apart. Losing it costs a partially-filled form, which is recoverable by the
visitor in front of the screen.

From step 4 the credit is a database row, and this is the load-bearing part.
`SignupView.form_valid` already calls `login(self.request, user)` — signup
auto-logs-in, because "the gate is on creating contributions, not on logging
in". So the account exists and the FK can be satisfied **before** the
verification email is ever opened. The mail round trip therefore carries no
state at all: verifying two days later, from a phone, on a different network,
works, because `verify_email` only has to flip a status on a row that is already
there.

This is why the design does not use the session for step 4→5. Checking mail on a
phone while filling a form on a laptop is the common case, not the edge case, and
a session-held credit is simply lost there.

## The pending status

`Contribution.Status` gains `PENDING = "pending"`, joining the already-dormant
`DISPUTED` and `REMOVED`. This is the spec's only migration.

Nothing outside `active` is displayed anywhere — the people search, the sitemap,
the game page, the company page and the profile all filter on
`status=Contribution.Status.ACTIVE` today. A pending credit is therefore
invisible to everyone including its author's own public profile, and becomes
visible at verification.

### The relaxation of design non-negotiable #6, stated plainly

Non-negotiable #6 is "email-verified gate enforced on contribution create". This
spec writes a contribution row before the email is verified. That is a real
departure from the letter of the rule and is recorded here rather than glossed:

- **What the rule protects** is that an unverified account cannot *publish*.
  That holds completely — a pending credit is displayed nowhere.
- **What changes** is that an unverified account can cause a row to exist.
- **The normal path is unchanged.** `/credits/new/` keeps
  `EmailVerifiedRequiredMixin` exactly as it is. A member who signs up through
  the ordinary route and then tries to add a credit before verifying is still
  bounced.

The asymmetry is deliberate and defensible: in the funnel the work was done by
an anonymous visitor *before* an account existed, so there was no unverified
user acting. Discarding that work to satisfy the letter of the rule would
destroy the only thing the feature exists to protect.

An account that never verifies leaves its pending row in place forever, invisible
to everyone. That is accepted: it is not published, it is covered by account
deletion (the FK is CASCADE), and it appears in the JSON export like any other
contribution.

## Routes

| Route | Name | Purpose |
|---|---|---|
| `/declare/` | `contributions:declare_game` | receives step 1, renders step 1 on its own for direct hits |
| `/declare/details/` | `contributions:declare_details` | the rest of the credit |
| `/declare/account/` | `contributions:declare_account` | signup, or "already have an account? log in" |

The steps live on their own paths and **not** on `/`. Only the step-1 field is
rendered on the root. This is not cosmetic: the previous spec made `/` bill
rate-limit quota to any request carrying a query string, and put `Disallow: /*?`
in robots.txt. Routing funnel steps through the root would collide with both —
a visitor answering three questions would spend search quota, and the funnel URLs
would sit inside the crawl-trap exclusion.

Each step redirects to the previous one if the session lacks what it needs, so a
direct hit on `/declare/details/` with an empty session lands on the question
rather than on a broken form.

All three live in the `contributions` app, step 3 included, even though that step
renders a signup form owned by `accounts`. The funnel is one flow with one piece
of session state and one outcome — a contribution — and splitting it across two
apps would put the state machine in two places to satisfy a filing rule. Step 3
imports `accounts.forms.SignupForm` rather than reimplementing it, so the account
rules stay owned by `accounts`.

## The root page

For anonymous visitors the funnel leads:

- the `<h1>` becomes **"Which game did you work on?"**, followed by one line of
  supporting copy — **"Add a credit to your name. You can create your account at
  the end."** — and the game field with a **"Continue"** button;
- the people search follows below, under an `<h2>` reading **"Looking for
  someone?"**;
- the pitch paragraph added by the previous spec is replaced by this block — the
  question does the pitch's job, actionably.

For authenticated members nothing changes: the funnel block does not render, the
`<h1>` stays "Find people by what they've worked on", and the page is exactly
what it is today. Members already have an account; the invitation is spent.

Two co-equal columns were considered and rejected. Making the visitor pick a side
before anything of value is delivered is a known dropoff, and on a narrow
viewport the columns stack into the same vertical order as the chosen layout
anyway, with worse headings.

### The SEO consequence, accepted knowingly

Crawlers are anonymous visitors, so Google will index the home page under
"Which game did you work on?" rather than "Find people by what they've worked
on". The site's homepage will read as an invitation to workers rather than a
description of a search tool.

This is the intended trade. Metric #1 is workers signing up; a recruiter arrives
with intent and will use the nav or scroll. It is written down because it is the
kind of change that is easy to make by accident and hard to notice afterwards.

## What an anonymous visitor cannot do

`search:game_autocomplete`, `search:company_autocomplete` and
`games:game_employers` are open to anonymous requests today, so steps 1 and 2
work without an account.

Three neighbouring endpoints are `@login_required` and **stay that way**:
`games:igdb_search`, `games:igdb_import` and `games:company_create`. All three
are write paths — two create a `Game`, one creates a `Company` — and one calls
the external IGDB API. Opening them to anonymous traffic would reopen exactly the
unauthenticated-write surface the project has otherwise avoided.

The consequences are handled in copy rather than by opening the endpoints:

- **Game not in the catalogue.** The seed holds ~392k games, so this is rare.
  Step 1 says so and offers the account as the way forward: "Can't find it?
  Create your account and we'll help you add it." The miss converts into a
  signup instead of a dead end.
- **Employer not listed.** The employer is optional on the credit form. An
  anonymous visitor who cannot find their studio leaves it blank and adds it
  after signing up.

## Verification becomes a reward

`verification_sent` today says "check your email". After the funnel it names what
is waiting: "Your credit on *<game>* is saved — verify your email to publish it."

The verification landing message changes the same way, from "you can now add
credits" to confirming the credit is live.

Same click, but it collects something rather than lifting a restriction. This
matters more than it looks: the verification step is the funnel's last exit, and
it is the one the visitor has the least reason to complete.

## Edge cases

- **Already has an account.** Step 3 offers "already have an account? Log in".
  The session survives login, so the pending credit is created immediately
  after, exactly as it is after signup.
- **Abandons mid-funnel.** Nothing is written. The session expires. No account,
  no row, no trace.
- **Already verified when the funnel completes.** Possible via the login path.
  The credit is created `active` directly — there is nothing to wait for.
- **A member who is already logged in hits `/declare/`.** The funnel still works
  and skips step 3.

## Testing

- The whole path: anonymous → game → details → signup → verify → the credit is
  on the public profile.
- A pending credit is absent from the people search, the sitemap, the game page,
  the company page and the author's own profile.
- Verification flips `pending` → `active`; a second verification is a no-op.
- The login entry point at step 3 produces the same result as the signup one.
- Abandoning writes nothing: no `User`, no `Contribution`.
- Anonymous `/` leads with the question; authenticated `/` does not render it.
- `/credits/new/` still bounces an unverified member — the relaxation is scoped
  to the funnel.
- A direct hit on `/declare/details/` with an empty session redirects rather
  than rendering a broken form.

## Deferred

**The referral loop.** A member who has declared working on a game names
colleagues (first name, surname, work email, role, optional dates); Rollcall
emails an invitation. Discussed and deferred on 2026-08-11. The version to build
is the one where the invitation link lands the invited person on a *pre-filled*
credit form — the data is shown only to the person it describes, and nothing
about a non-consenting individual is ever displayed publicly.

The variant that publishes a "pending credits" list on game and company pages is
**not** the one to build: hiding it from search and the sitemap does not contain
it, because a game page is itself public. That variant contradicts the rule set
here — nobody writes another person's credit — and pulls in GDPR Article 14
notification, mandatory counsel review, a moderation queue and person-record
merging.

Four frictions to carry into that spec: holding a third party's work email;
handing users an email-sending primitive from the Rollcall domain (the contact
relay's per-sender DB-backed limit is the precedent); pending credits without an
email having no claim channel and therefore no business existing; and duplicate
person records when several colleagues name the same person.

## Not doing

- No way to record anything about another person (see *Deferred*).
- No change to the people search, its filters, results or pagination.
- No change to `/credits/new/`, `EmailVerifiedRequiredMixin`, or the credit form
  itself — the funnel reuses `ContributionForm`'s fields and validation.
- No new write endpoint open to anonymous requests.
- No vouching UI. `Vouch` stays dormant and positive-only.

# Security policy

Rollcall stores personal data about real people in an industry with
documented harassment risks. We take reports seriously and we want them
private first.

## Reporting a vulnerability

**Do not open a public issue for a security or privacy problem.**

Use GitHub's private vulnerability reporting on this repository
(<https://github.com/Hushcrasher/rollcall> — "Security" tab → "Report a
vulnerability"). If that is unavailable to you, contact the maintainers
privately through their GitHub profiles.

Especially important to us, straight from the project's non-negotiables:

- any way to read a member's **account email address** (the one they sign in
  with) through any page, endpoint, header, export or search response — the
  opt-in contact address a member chooses to show on their profile is by
  design;
- any way to see a **private profile** (`profile_public=False`) or a
  non-`active` credit anywhere public;
- any way to write another person's data (credits, profile fields);
- abuse vectors in the **contact relay** (it sends real email).

## What to expect

We aim to acknowledge reports within a few days. This is a small
pre-launch project — there is no bug bounty — but reporters get credited
in the fix's release notes if they wish.

## Scope notes

Rate limits are documented as *mitigations, not boundaries*
(docs/01-DESIGN.md §3.6): "the search can be enumerated slowly despite the
rate limit" is a known, accepted property, not a vulnerability. The
≥1-filter form rule is a UX guard and is likewise not a security boundary.

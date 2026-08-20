# Contributing to Rollcall

Thanks for your interest! A few ground rules:

## Developer Certificate of Origin (DCO)

We use the [DCO](https://developercertificate.org/) instead of a CLA. Every
commit must be signed off:

```bash
git commit -s -m "feat: my change"
```

The `Signed-off-by:` trailer certifies you have the right to submit the code
under the project's license (AGPL v3). **CI enforces this on every PR commit**
— an unsigned commit fails the `dco` check.

## Getting started

```bash
docker compose up          # app + Postgres
# or natively:
uv sync && uv run python manage.py migrate && uv run python manage.py runserver
```

Contributors have no access to the production parquet source: load the dev
fixtures instead (see README). A fork must be able to plug its own game
source — that's the cleanliness test we hold ourselves to. The fork boundary
is the prepared-parquet contract in [games/seed/schema.py](games/seed/schema.py):
point `PARQUET_SOURCE_URL` at any parquet with those columns, however you
produced it (Hushcrasher's own prepare step, `games/seed/prepare.py`, is
specific to our raw files and yours to ignore).

## Where things live

One Django app per domain: `accounts` (users, profiles, GDPR),
`games` (catalog, seed pipeline under `games/seed/`, IGDB fallback),
`contributions` (credits + the declare funnel), `search` (ALL search logic —
`search/services.py` is the only place queries live), `contact` (relay +
reports). Shared templates in `templates/`; each recent feature has a design
record in `docs/superpowers/specs/` explaining why it looks the way it does.

**Specs vs plans:** files in `docs/superpowers/specs/` are binding design
records — read the spec for any surface you touch. Files in
`docs/superpowers/plans/` are historical execution logs; you can ignore them.

## Review & merge process

A maintainer reviews every PR; merges are squash merges to `main`; `main`
deploys. There is no release schedule during the POC. Behavior changes must
update `docs/01-DESIGN.md` and `ROADMAP.md` in the same PR — the docs are
load-bearing here, not decoration.

## Quality bar

- Python is **fully typed**: annotate every function, method and fixture.
  Toolchain is the Astral stack — uv (packages), ruff (lint + format),
  ty (type checking).
- `uv run ruff check . && uv run ruff format --check .` must pass.
- `uv run ty check` must pass.
- `uv run pytest` must pass. New behavior comes with tests; the seed dedup,
  recruiter search query, and account deletion paths are non-negotiable
  test zones (docs/02-ARCHITECTURE.md §7).
- All user-facing strings go through Django i18n (`gettext`/`{% translate %}`).
- Never expose a personal email anywhere. Never add public negative signals.

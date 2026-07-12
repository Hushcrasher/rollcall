# Contributing to Rollcall

Thanks for your interest! A few ground rules:

## Developer Certificate of Origin (DCO)

We use the [DCO](https://developercertificate.org/) instead of a CLA. Every
commit must be signed off:

```bash
git commit -s -m "feat: my change"
```

The `Signed-off-by:` trailer certifies you have the right to submit the code
under the project's license (AGPL v3).

## Getting started

```bash
docker compose up          # app + Postgres
# or natively:
uv sync && uv run python manage.py migrate && uv run python manage.py runserver
```

Contributors have no access to the production parquet source: load the dev
fixtures instead (see README). A fork must be able to plug its own game
source — that's the cleanliness test we hold ourselves to.

## Quality bar

- `uv run ruff check . && uv run ruff format --check .` must pass.
- `uv run pytest` must pass. New behavior comes with tests; the seed dedup,
  recruiter search query, and account deletion paths are non-negotiable
  test zones (docs/02-ARCHITECTURE.md §7).
- All user-facing strings go through Django i18n (`gettext`/`{% translate %}`).
- Never expose a personal email anywhere. Never add public negative signals.

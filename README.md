# Rollcall

A credits and discovery database for the video game industry — people, games,
companies. "LinkedIn for the game industry" **without the social network part**:
workers declare their contributions ("I worked on game X as [role], from A to B"),
peers can later confirm them, and recruiters search people by properties of the
games they worked on (engine, genre, ratings, discipline, dates).

> **Transparency:** the code is open source under **AGPL v3**; the production
> database is private and operated by **Hushcrasher**. Users own their data.

## Project status

Proof of concept, in active development. See [ROADMAP.md](ROADMAP.md) for what
is done and what is next, and [docs/](docs/00-README.md) for the full design pack:

| Doc | Content |
|---|---|
| [docs/01-DESIGN.md](docs/01-DESIGN.md) | Product vision and validated decisions — **source of truth for behavior** |
| [docs/02-ARCHITECTURE.md](docs/02-ARCHITECTURE.md) | System architecture, seed pipeline, infra, testing priorities |
| [docs/03-TECH-STACK.md](docs/03-TECH-STACK.md) | Technology choices and rationale |
| [docs/04-DATABASE-SCHEMA.md](docs/04-DATABASE-SCHEMA.md) | Table-by-table schema, GDPR behavior |

## Stack

Django monolith (server-rendered templates + htmx) · PostgreSQL 16 ·
DuckDB-powered batch seed from a parquet source · Docker · deployed on
Railway + Cloudflare R2 (EU regions; see [DEPLOY.md](DEPLOY.md)).

## Development

With Docker (recommended for a first run):

```bash
docker compose up
# app on http://localhost:8000 — Postgres on localhost:5432
# (port taken? put POSTGRES_PORT=5433 in .env)
```

Then, in a second terminal, load the fake dataset — without it the app runs
on an empty database:

```bash
docker compose exec web python manage.py load_dev_fixtures
```

Natively with [uv](https://docs.astral.sh/uv/) (Postgres required, e.g. `docker compose up db`):

```bash
cp .env.example .env          # optional in dev — every value may stay blank
uv sync
uv run python manage.py migrate
uv run python manage.py load_dev_fixtures   # fake games/users/credits (dev only)
uv run python manage.py runserver
```

Quality checks:

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest
```

Contributors don't need access to the production parquet source —
`load_dev_fixtures` creates a deterministic fake dataset (games, companies,
profiles, credits) in one command. See [CONTRIBUTING.md](CONTRIBUTING.md)
(DCO required).

## Non-negotiable product rules

1. Personal emails are never displayed or exposed anywhere — contact happens
   only through a relay (Reply-To pattern).
2. No public negative signals of any kind (no down-votes, no public "disputed"
   labels, no numeric trust scores).
3. The app's Postgres is autonomous; no application code reads the parquet —
   only the seed management command does.
4. Account deletion fully works: contributions cascade, vouches anonymized,
   JSON export available.

The full list lives in [docs/00-README.md](docs/00-README.md).

## License and copyright

Copyright (C) 2026 Hushcrasher.

Rollcall is free software: you can redistribute it and/or modify it under the
terms of the GNU Affero General Public License, version 3, as published by the
Free Software Foundation. See [LICENSE](LICENSE). Source:
<https://github.com/Micro-SAS/rollcall>.

**What the licence covers — and what it does not.** The AGPL covers the
*software*: this code, its templates and its design. It does not cover, and
this repository does not contain, any data of the production service: the game
catalog Hushcrasher assembles, and everything users submit — credits, profiles,
images, contact requests. That data lives in a private database operated solely
by Hushcrasher, under the Terms of Service and Privacy Policy published on the
service; users own their contributions. Anyone may run their own instance of
this software — with their own database.

**Contributions** are accepted under the [DCO](CONTRIBUTING.md): contributors
keep the copyright on their work and license it under the same AGPL v3 terms.
There is no CLA and no copyright assignment.

## Attribution

Game metadata © IGDB.com / Twitch, used under their API terms.

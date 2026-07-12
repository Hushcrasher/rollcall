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
DuckDB-powered batch seed from a parquet source · Docker · deployed on an EU PaaS.

## Development

With Docker (recommended for a first run):

```bash
docker compose up
# app on http://localhost:8000, Postgres on localhost:5432
```

Natively with [uv](https://docs.astral.sh/uv/) (Postgres required, e.g. `docker compose up db`):

```bash
cp .env.example .env          # fill in DJANGO_SECRET_KEY at least
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

Quality checks:

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest
```

Contributors don't need access to the production parquet source — dev fixtures
(fake games and profiles) are loadable in one command (coming with the schema
phase, see ROADMAP.md). See [CONTRIBUTING.md](CONTRIBUTING.md) (DCO required).

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

## License

[AGPL v3](LICENSE).

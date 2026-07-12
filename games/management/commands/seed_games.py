"""`python manage.py seed_games` — the weekly batch seed (docs/02-ARCHITECTURE.md §3).

Reads Hushcrasher's remote parquet with DuckDB (HTTP/S3, constant memory),
performs the Steam↔IGDB dedup/merge in SQL, then upserts into Postgres in
batches (INSERT ... ON CONFLICT (igdb_id) DO UPDATE, and by steam_appid for
Steam-only rows). Idempotent: first run = initial seed, later runs = refresh.

Write-surface is strictly limited to [source] columns — see
docs/04-DATABASE-SCHEMA.md §13. Never touches platform-owned data.

Implementation comes in the seed phase (ROADMAP.md), AFTER the blocking
prerequisites: IGDB/Steam ToS written confirmation + parquet audit.
"""

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Seed/refresh the games database from the parquet source (idempotent)."

    def handle(self, *args: Any, **options: Any) -> None:
        raise NotImplementedError("seed_games is not implemented yet — see ROADMAP.md, seed phase.")

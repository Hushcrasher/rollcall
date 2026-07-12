"""`python manage.py seed_games` — the weekly batch seed (docs/02-ARCHITECTURE.md §3).

Reads Hushcrasher's parquet with DuckDB, dedups Steam↔IGDB in SQL, then upserts
into Postgres. Idempotent: first run = initial seed, later runs = weekly refresh.

Launcher-agnostic: the PaaS scheduler runs it with no arguments (source comes
from PARQUET_SOURCE_URL); a Prefect flow could invoke it with `--source` later.
Failure handling is logs + an optional email alert — no orchestration framework.

Write-surface is strictly limited to [source] columns (docs/04 §13); see
`games/seed/`.
"""

import logging
from typing import Any

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError, CommandParser

from games.seed.pipeline import iter_canonical_games
from games.seed.upsert import upsert_games

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Seed/refresh the games database from the parquet source (idempotent)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--source",
            dest="source",
            default=None,
            help="Parquet URL or path. Defaults to settings.PARQUET_SOURCE_URL.",
        )
        parser.add_argument("--batch-size", dest="batch_size", type=int, default=500)

    def handle(self, *args: Any, **options: Any) -> None:
        source = options.get("source") or settings.PARQUET_SOURCE_URL
        if not source:
            raise CommandError(
                "No parquet source configured: set PARQUET_SOURCE_URL or pass --source."
            )

        batch_size = options["batch_size"]
        self.stdout.write(f"Seeding games from {source} …")
        try:
            stats = upsert_games(
                iter_canonical_games(source, batch_size=batch_size), batch_size=batch_size
            )
        except Exception as exc:
            logger.exception("seed_games failed")
            self._alert_failure(source, exc)
            raise CommandError(f"seed_games failed: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete: {stats['created']} created, {stats['updated']} updated."
            )
        )

    def _alert_failure(self, source: str, exc: Exception) -> None:
        recipient = settings.SEED_ALERT_EMAIL
        if not recipient:
            return
        try:
            send_mail(
                subject="[Rollcall] Seed job failed",
                message=f"seed_games failed reading {source}:\n\n{exc!r}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
            )
        except Exception:  # alerting must never mask the original failure
            logger.exception("Failed to send seed-failure alert email")

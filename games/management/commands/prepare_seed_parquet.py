"""`python manage.py prepare_seed_parquet` — build the seed parquet from source files.

Joins Hushcrasher's normalized source files (IGDB + Steam) into one
`rollcall_games.parquet` that `seed_games` then loads. Run wherever the raw
data lives; upload the result to R2 and point PARQUET_SOURCE_URL at it.

Expects, under --source-dir:
  igdb/igdb_games.parquet, igdb/igdb_release_dates.parquet,
  hushcrasher.parquet, steamdb.parquet
"""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from games.seed.prepare import prepare_seed_parquet


class Command(BaseCommand):
    help = "Join the IGDB/Steam source files into one prepared seed parquet."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--source-dir", default="data", help="Directory holding the raw parquet files."
        )
        parser.add_argument(
            "--out", default="data/rollcall_games.parquet", help="Output parquet path."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        source = Path(options["source_dir"])
        files = {
            "igdb": source / "igdb" / "igdb_games.parquet",
            "release_dates": source / "igdb" / "igdb_release_dates.parquet",
            "hushcrasher": source / "hushcrasher.parquet",
            "steamdb": source / "steamdb.parquet",
        }
        missing = [str(p) for p in files.values() if not p.exists()]
        if missing:
            raise CommandError("Missing source file(s):\n  " + "\n  ".join(missing))

        self.stdout.write("Joining source files … (this reads ~900MB, give it a minute)")
        count = prepare_seed_parquet(
            igdb=str(files["igdb"]),
            hushcrasher=str(files["hushcrasher"]),
            steamdb=str(files["steamdb"]),
            release_dates=str(files["release_dates"]),
            out_path=options["out"],
        )
        self.stdout.write(
            self.style.SUCCESS(f"Wrote {count:,} games to {options['out']}. Now run: seed_games")
        )

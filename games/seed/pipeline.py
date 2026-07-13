"""Read the prepared parquet and stream canonical games.

The Steam↔IGDB merge already happened in `prepare.py` (a DuckDB join over the
normalized source files), so this is a straight projection — one row in, one
CanonicalGame out. Constant memory: rows stream via fetchmany.
"""

import os
import urllib.error
from collections.abc import Iterator
from typing import Any

import duckdb

from games.seed import schema
from games.seed.schema import CanonicalGame

# Column order for the projection — matches CanonicalGame's field order so rows
# map positionally.
_SELECT_COLUMNS = [name for name, _ in schema.PARQUET_COLUMNS]

_READ_SQL = f"SELECT {', '.join(_SELECT_COLUMNS)} FROM read_parquet(?)"


def configure_remote_access(con: duckdb.DuckDBPyConnection, source: str) -> None:
    """Enable httpfs + S3 credentials when the source is a remote URL (R2)."""
    if not source.startswith(("s3://", "http://", "https://")):
        return
    con.execute("INSTALL httpfs; LOAD httpfs;")
    if source.startswith("s3://"):
        endpoint = os.environ.get("S3_ENDPOINT_URL", "")
        if endpoint:
            con.execute(
                "SET s3_endpoint = ?", [endpoint.replace("https://", "").replace("http://", "")]
            )
        for setting, env in (
            ("s3_access_key_id", "S3_ACCESS_KEY_ID"),
            ("s3_secret_access_key", "S3_SECRET_ACCESS_KEY"),
            ("s3_region", "S3_REGION"),
        ):
            value = os.environ.get(env)
            if value:
                con.execute(f"SET {setting} = ?", [value])


def _to_canonical(row: tuple[Any, ...]) -> CanonicalGame:
    return CanonicalGame(
        igdb_id=row[0],
        steam_appid=row[1],
        title=row[2],
        release_date=row[3],
        summary=row[4] or "",
        cover_url=row[5] or "",
        igdb_rating=row[6],
        igdb_aggregated_rating=row[7],
        steam_positive_pct=row[8],
        steam_review_count=row[9],
        genres=list(row[10] or []),
        engines=list(row[11] or []),
        developers=list(row[12] or []),
        publishers=list(row[13] or []),
        porting=list(row[14] or []),
        supporting=list(row[15] or []),
    )


def iter_canonical_games(source: str, batch_size: int = 1000) -> Iterator[CanonicalGame]:
    """Stream canonical games from the prepared parquet, constant memory."""
    con = duckdb.connect()
    try:
        configure_remote_access(con, source)
        result = con.execute(_READ_SQL, [source])
        while batch := result.fetchmany(batch_size):
            for row in batch:
                yield _to_canonical(row)
    except (duckdb.Error, urllib.error.URLError) as exc:
        raise RuntimeError(f"Failed to read parquet {source}: {exc}") from exc
    finally:
        con.close()


def read_canonical_games(source: str) -> list[CanonicalGame]:
    """Eager variant of `iter_canonical_games` — convenient for tests."""
    return list(iter_canonical_games(source))

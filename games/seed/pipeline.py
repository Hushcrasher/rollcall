"""DuckDB read + Steam↔IGDB dedup/merge — the SQL heart of the seed.

Reads a parquet (local path, or HTTP/S3 URL via httpfs), merges the IGDB and
Steam representations of each game in SQL, and yields canonical games. Constant
memory: rows are streamed with fetchmany, never materialized all at once.
"""

import os
from collections.abc import Iterator
from typing import Any

import duckdb

from games.seed import schema
from games.seed.schema import CanonicalGame

# Explicit column order for the final projection — must match CanonicalGame's
# field order so we can map rows positionally.
_SELECT_COLUMNS = [
    schema.COL_IGDB_ID,
    schema.COL_STEAM_APPID,
    schema.COL_TITLE,
    schema.COL_RELEASE_DATE,
    schema.COL_SUMMARY,
    schema.COL_COVER_URL,
    schema.COL_IGDB_RATING,
    schema.COL_IGDB_AGGREGATED_RATING,
    schema.COL_STEAM_POSITIVE_PCT,
    schema.COL_STEAM_REVIEW_COUNT,
    schema.COL_GENRES,
    schema.COL_ENGINES,
    schema.COL_DEVELOPERS,
    schema.COL_PUBLISHERS,
    schema.COL_PORTING,
    schema.COL_SUPPORTING,
]

# The merge (docs/02-ARCHITECTURE.md §3):
#   - dedup within each system (QUALIFY keeps one row per igdb_id / steam_appid),
#   - IGDB rows are canonical; their Steam review stats come from the matching
#     Steam row (LEFT JOIN on steam_appid),
#   - Steam rows whose appid no IGDB row claims become Steam-only canonical games.
_MERGE_SQL = f"""
WITH src AS (
    SELECT * FROM read_parquet(?)
),
igdb AS (
    SELECT * FROM src
    WHERE {schema.COL_SOURCE_KIND} = '{schema.SOURCE_KIND_IGDB}'
    QUALIFY row_number() OVER (
        PARTITION BY {schema.COL_IGDB_ID}
        ORDER BY {schema.COL_STEAM_APPID} NULLS LAST, {schema.COL_TITLE}
    ) = 1
),
steam AS (
    SELECT * FROM src
    WHERE {schema.COL_SOURCE_KIND} = '{schema.SOURCE_KIND_STEAM}'
    QUALIFY row_number() OVER (
        PARTITION BY {schema.COL_STEAM_APPID}
        ORDER BY {schema.COL_TITLE}
    ) = 1
),
linked_appids AS (
    SELECT DISTINCT {schema.COL_STEAM_APPID} AS appid
    FROM igdb WHERE {schema.COL_STEAM_APPID} IS NOT NULL
),
canonical AS (
    SELECT
        i.{schema.COL_IGDB_ID}                 AS {schema.COL_IGDB_ID},
        i.{schema.COL_STEAM_APPID}             AS {schema.COL_STEAM_APPID},
        i.{schema.COL_TITLE}                   AS {schema.COL_TITLE},
        i.{schema.COL_RELEASE_DATE}            AS {schema.COL_RELEASE_DATE},
        i.{schema.COL_SUMMARY}                 AS {schema.COL_SUMMARY},
        i.{schema.COL_COVER_URL}               AS {schema.COL_COVER_URL},
        i.{schema.COL_IGDB_RATING}             AS {schema.COL_IGDB_RATING},
        i.{schema.COL_IGDB_AGGREGATED_RATING}  AS {schema.COL_IGDB_AGGREGATED_RATING},
        s.{schema.COL_STEAM_POSITIVE_PCT}      AS {schema.COL_STEAM_POSITIVE_PCT},
        s.{schema.COL_STEAM_REVIEW_COUNT}      AS {schema.COL_STEAM_REVIEW_COUNT},
        i.{schema.COL_GENRES}                  AS {schema.COL_GENRES},
        i.{schema.COL_ENGINES}                 AS {schema.COL_ENGINES},
        i.{schema.COL_DEVELOPERS}              AS {schema.COL_DEVELOPERS},
        i.{schema.COL_PUBLISHERS}              AS {schema.COL_PUBLISHERS},
        i.{schema.COL_PORTING}                 AS {schema.COL_PORTING},
        i.{schema.COL_SUPPORTING}              AS {schema.COL_SUPPORTING}
    FROM igdb i
    LEFT JOIN steam s ON s.{schema.COL_STEAM_APPID} = i.{schema.COL_STEAM_APPID}

    UNION ALL

    SELECT
        NULL::BIGINT,
        s.{schema.COL_STEAM_APPID},
        s.{schema.COL_TITLE},
        s.{schema.COL_RELEASE_DATE},
        s.{schema.COL_SUMMARY},
        s.{schema.COL_COVER_URL},
        NULL::DOUBLE,
        NULL::DOUBLE,
        s.{schema.COL_STEAM_POSITIVE_PCT},
        s.{schema.COL_STEAM_REVIEW_COUNT},
        []::VARCHAR[],
        []::VARCHAR[],
        s.{schema.COL_DEVELOPERS},
        s.{schema.COL_PUBLISHERS},
        s.{schema.COL_PORTING},
        s.{schema.COL_SUPPORTING}
    FROM steam s
    WHERE s.{schema.COL_STEAM_APPID} NOT IN (SELECT appid FROM linked_appids)
)
SELECT {", ".join(_SELECT_COLUMNS)}
FROM canonical
ORDER BY {schema.COL_IGDB_ID} NULLS LAST, {schema.COL_STEAM_APPID} NULLS LAST
"""


def _configure_remote_access(con: duckdb.DuckDBPyConnection, source: str) -> None:
    """Enable httpfs + S3 credentials when the source is a remote URL."""
    if not (source.startswith(("s3://", "http://", "https://"))):
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
    """Stream deduplicated games from the parquet at `source`, constant memory."""
    con = duckdb.connect()
    try:
        _configure_remote_access(con, source)
        result = con.execute(_MERGE_SQL, [source])
        while batch := result.fetchmany(batch_size):
            for row in batch:
                yield _to_canonical(row)
    finally:
        con.close()


def read_canonical_games(source: str) -> list[CanonicalGame]:
    """Eager variant of `iter_canonical_games` — convenient for tests."""
    return list(iter_canonical_games(source))

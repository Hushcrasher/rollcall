"""The parquet contract — what the seed EXPECTS to read.

This is the source-agnostic boundary of the project (docs/02-ARCHITECTURE.md
§2.5): a fork points PARQUET_SOURCE_URL at any parquet that provides these
columns. Derived from docs/04-DATABASE-SCHEMA.md §3–6.

Shape: one row per (game, originating system). A single real game may appear
as up to two rows — its IGDB representation and its Steam representation —
linked by `steam_appid`; the pipeline merges them (see `pipeline.py`).

If Hushcrasher's real parquet uses different column names, adjust the
constants here and the `read_parquet` projection in `pipeline.py`; no other
code changes.
"""

from dataclasses import dataclass, field
from datetime import date

# --- Column names (edit these to match a real parquet) ----------------------

COL_SOURCE_KIND = "source_kind"  # 'igdb' | 'steam' — which system this row is
COL_IGDB_ID = "igdb_id"
COL_STEAM_APPID = "steam_appid"
COL_TITLE = "title"
COL_RELEASE_DATE = "release_date"
COL_SUMMARY = "summary"
COL_COVER_URL = "cover_url"
COL_IGDB_RATING = "igdb_rating"
COL_IGDB_AGGREGATED_RATING = "igdb_aggregated_rating"
COL_STEAM_POSITIVE_PCT = "steam_positive_pct"
COL_STEAM_REVIEW_COUNT = "steam_review_count"
COL_GENRES = "genres"  # VARCHAR[] — IGDB taxonomy names
COL_ENGINES = "engines"  # VARCHAR[] — IGDB taxonomy names
COL_DEVELOPERS = "developers"  # VARCHAR[] — company names
COL_PUBLISHERS = "publishers"  # VARCHAR[]
COL_PORTING = "porting"  # VARCHAR[]
COL_SUPPORTING = "supporting"  # VARCHAR[]

SOURCE_KIND_IGDB = "igdb"
SOURCE_KIND_STEAM = "steam"

# Ordered (name, DuckDB type) contract — also used to build synthetic parquets.
PARQUET_COLUMNS: list[tuple[str, str]] = [
    (COL_SOURCE_KIND, "VARCHAR"),
    (COL_IGDB_ID, "BIGINT"),
    (COL_STEAM_APPID, "BIGINT"),
    (COL_TITLE, "VARCHAR"),
    (COL_RELEASE_DATE, "DATE"),
    (COL_SUMMARY, "VARCHAR"),
    (COL_COVER_URL, "VARCHAR"),
    (COL_IGDB_RATING, "DOUBLE"),
    (COL_IGDB_AGGREGATED_RATING, "DOUBLE"),
    (COL_STEAM_POSITIVE_PCT, "DOUBLE"),
    (COL_STEAM_REVIEW_COUNT, "BIGINT"),
    (COL_GENRES, "VARCHAR[]"),
    (COL_ENGINES, "VARCHAR[]"),
    (COL_DEVELOPERS, "VARCHAR[]"),
    (COL_PUBLISHERS, "VARCHAR[]"),
    (COL_PORTING, "VARCHAR[]"),
    (COL_SUPPORTING, "VARCHAR[]"),
]


@dataclass(frozen=True)
class CanonicalGame:
    """One deduplicated game — the pipeline's output, ready for upsert.

    `igdb_id` and `steam_appid` are the upsert keys (at least one is non-null).
    List fields carry the seed-owned link data (genres/engines/companies).
    """

    igdb_id: int | None
    steam_appid: int | None
    title: str
    release_date: date | None
    summary: str
    cover_url: str
    igdb_rating: float | None
    igdb_aggregated_rating: float | None
    steam_positive_pct: float | None
    steam_review_count: int | None
    genres: list[str] = field(default_factory=list)
    engines: list[str] = field(default_factory=list)
    developers: list[str] = field(default_factory=list)
    publishers: list[str] = field(default_factory=list)
    porting: list[str] = field(default_factory=list)
    supporting: list[str] = field(default_factory=list)

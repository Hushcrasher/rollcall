"""Write synthetic parquets for seed tests — no real parquet needed."""

from pathlib import Path
from typing import Any

import duckdb

from games.seed import schema


def _igdb_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {name: None for name, _ in schema.PARQUET_COLUMNS}
    row.update(
        {
            schema.COL_SOURCE_KIND: schema.SOURCE_KIND_IGDB,
            schema.COL_TITLE: "Untitled",
            schema.COL_SUMMARY: "",
            schema.COL_COVER_URL: "",
            schema.COL_GENRES: [],
            schema.COL_ENGINES: [],
            schema.COL_DEVELOPERS: [],
            schema.COL_PUBLISHERS: [],
            schema.COL_PORTING: [],
            schema.COL_SUPPORTING: [],
        }
    )
    row.update(overrides)
    return row


def igdb_row(igdb_id: int, **overrides: Any) -> dict[str, Any]:
    """An IGDB-originated parquet row (may also carry a steam_appid mapping)."""
    return _igdb_row(igdb_id=igdb_id, **overrides)


def steam_row(steam_appid: int, **overrides: Any) -> dict[str, Any]:
    """A Steam-originated parquet row (no igdb_id; carries review stats)."""
    return _igdb_row(
        **{
            schema.COL_SOURCE_KIND: schema.SOURCE_KIND_STEAM,
            schema.COL_STEAM_APPID: steam_appid,
            **overrides,
        }
    )


def write_parquet(path: Path | str, rows: list[dict[str, Any]]) -> str:
    """Write `rows` to a parquet at `path` following the column contract."""
    con = duckdb.connect()
    try:
        columns_ddl = ", ".join(f'"{name}" {dtype}' for name, dtype in schema.PARQUET_COLUMNS)
        con.execute(f"CREATE TABLE g ({columns_ddl})")
        placeholders = ", ".join("?" for _ in schema.PARQUET_COLUMNS)
        ordered = [[row[name] for name, _ in schema.PARQUET_COLUMNS] for row in rows]
        if ordered:
            con.executemany(f"INSERT INTO g VALUES ({placeholders})", ordered)
        con.execute(f"COPY g TO '{path}' (FORMAT PARQUET)")
    finally:
        con.close()
    return str(path)

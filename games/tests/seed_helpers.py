"""Write synthetic prepared parquets for seed tests — no catalog file needed."""

from pathlib import Path
from typing import Any

import duckdb

from games.seed import schema


def game_row(**overrides: Any) -> dict[str, Any]:
    """One prepared-parquet row (already-merged canonical game)."""
    row: dict[str, Any] = dict.fromkeys(name for name, _ in schema.PARQUET_COLUMNS)
    row.update(
        {
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


def write_typed_parquet(
    path: Path | str, columns: list[tuple[str, str]], rows: list[dict[str, Any]]
) -> str:
    """Write `rows` to a parquet with the given (name, DuckDB type) columns.
    Used to fake the raw IGDB/Steam source files in prepare tests."""
    con = duckdb.connect()
    try:
        ddl = ", ".join(f'"{name}" {dtype}' for name, dtype in columns)
        con.execute(f"CREATE TABLE t ({ddl})")
        placeholders = ", ".join("?" for _ in columns)
        ordered = [[row.get(name) for name, _ in columns] for row in rows]
        if ordered:
            con.executemany(f"INSERT INTO t VALUES ({placeholders})", ordered)
        con.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")
    finally:
        con.close()
    return str(path)


def write_prepared_parquet(path: Path | str, rows: list[dict[str, Any]]) -> str:
    """Write `rows` to a parquet following the prepared-parquet column contract."""
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

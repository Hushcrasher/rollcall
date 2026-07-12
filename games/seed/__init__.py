"""Seed pipeline — DuckDB reads a parquet, dedups Steam↔IGDB, upserts Postgres.

This package is the ONLY code that reads the parquet (docs/02-ARCHITECTURE.md
§2.1). It is source-agnostic: a fork plugs its own parquet at PARQUET_SOURCE_URL
as long as it matches the contract documented in `schema.py`.
"""

"""Prepare the seed parquet — the Steam↔IGDB merge, in DuckDB.

Joins Hushcrasher's normalized source files into ONE `rollcall_games.parquet`
matching the prepared-parquet contract (`schema.py`). This is where the messy
multi-file join lives, cleanly separated from the app; the seed then just
upserts the result.

Canonical set (docs/01-DESIGN.md §3.1): every IGDB game (Steam-linked or not),
plus Steam games with no IGDB entry. A game with no Steam link simply has null
Steam-review columns.

Sources (real column names; adjust here if the upstream files change):
- igdb_games:    igdb_id, steam_app_id, game_name, summary, engine_names[],
                 developer_names[], publisher_names[]
- hushcrasher:   app_id, name, review_score (Steam positive %), reviews_steam,
                 genres[], game_engines[], developers[], publishers[],
                 steam_release_date, about_the_game
- steam:         steam_appid, name, header_image, short_description
- release_dates: igdb_id, date
"""

import duckdb

from games.seed.pipeline import configure_remote_access


def _clean_names(expr: str, limit: int) -> str:
    """Trim + truncate each name to the DB column limit and drop blanks —
    real dev/publisher/genre names carry stray whitespace and garbage."""
    return (
        f"list_filter("
        f"  list_transform({expr}, x -> left(trim(x), {limit})),"
        f"  y -> y IS NOT NULL AND y <> '')"
    )


def _build_sql(igdb: str, hushcrasher: str, steam: str, release_dates: str) -> str:
    genres_ig = _clean_names("COALESCE(hc.genres, []::VARCHAR[])", 100)
    engines_ig = _clean_names(
        "COALESCE(NULLIF(ig.engine_names, []::VARCHAR[]), hc.game_engines, []::VARCHAR[])", 100
    )
    developers_ig = _clean_names(
        "COALESCE(NULLIF(ig.developer_names, []::VARCHAR[]), hc.developers, []::VARCHAR[])", 300
    )
    publishers_ig = _clean_names(
        "COALESCE(NULLIF(ig.publisher_names, []::VARCHAR[]), hc.publishers, []::VARCHAR[])", 300
    )
    genres_so = _clean_names("COALESCE(hc.genres, []::VARCHAR[])", 100)
    engines_so = _clean_names("COALESCE(hc.game_engines, []::VARCHAR[])", 100)
    developers_so = _clean_names("COALESCE(hc.developers, []::VARCHAR[])", 300)
    publishers_so = _clean_names("COALESCE(hc.publishers, []::VARCHAR[])", 300)
    return f"""
WITH first_release AS (
    SELECT igdb_id, min(date) AS release_date
    FROM read_parquet('{release_dates}') WHERE date IS NOT NULL GROUP BY igdb_id
),
igdb AS (
    SELECT * FROM read_parquet('{igdb}') WHERE game_name IS NOT NULL
    QUALIFY row_number() OVER (PARTITION BY igdb_id ORDER BY steam_app_id NULLS LAST) = 1
),
hc AS (
    SELECT * FROM read_parquet('{hushcrasher}') WHERE name IS NOT NULL
    QUALIFY row_number() OVER (PARTITION BY app_id ORDER BY reviews_steam DESC NULLS LAST) = 1
),
sd AS (
    SELECT * FROM read_parquet('{steam}')
    QUALIFY row_number() OVER (PARTITION BY steam_appid ORDER BY steam_appid) = 1
),
linked AS (
    SELECT DISTINCT steam_app_id AS appid FROM igdb WHERE steam_app_id IS NOT NULL
),
igdb_games AS (
    SELECT
        ig.igdb_id                                                       AS igdb_id,
        ig.steam_app_id                                                  AS steam_appid,
        left(ig.game_name, 500)                                          AS title,
        COALESCE(fr.release_date, CAST(hc.steam_release_date AS DATE))   AS release_date,
        COALESCE(NULLIF(ig.summary, ''), sd.short_description, '')        AS summary,
        left(COALESCE(sd.header_image, ''), 500)                          AS cover_url,
        NULL::DOUBLE                                                      AS igdb_rating,
        NULL::DOUBLE                                                      AS igdb_aggregated_rating,
        CAST(hc.review_score AS DOUBLE)                                   AS steam_positive_pct,
        CAST(hc.reviews_steam AS BIGINT)                                  AS steam_review_count,
        {genres_ig}                                                      AS genres,
        {engines_ig}                                                     AS engines,
        {developers_ig}                                                  AS developers,
        {publishers_ig}                                                  AS publishers,
        []::VARCHAR[]                                                     AS porting,
        []::VARCHAR[]                                                     AS supporting
    FROM igdb ig
    LEFT JOIN hc ON hc.app_id = ig.steam_app_id
    LEFT JOIN sd ON sd.steam_appid = ig.steam_app_id
    LEFT JOIN first_release fr ON fr.igdb_id = ig.igdb_id
),
steam_only AS (
    SELECT
        NULL::BIGINT                                       AS igdb_id,
        hc.app_id                                          AS steam_appid,
        left(hc.name, 500)                                 AS title,
        CAST(hc.steam_release_date AS DATE)                AS release_date,
        COALESCE(sd.short_description, hc.about_the_game, '') AS summary,
        left(COALESCE(sd.header_image, ''), 500)           AS cover_url,
        NULL::DOUBLE                                       AS igdb_rating,
        NULL::DOUBLE                                       AS igdb_aggregated_rating,
        CAST(hc.review_score AS DOUBLE)                    AS steam_positive_pct,
        CAST(hc.reviews_steam AS BIGINT)                   AS steam_review_count,
        {genres_so}                                        AS genres,
        {engines_so}                                       AS engines,
        {developers_so}                                    AS developers,
        {publishers_so}                                    AS publishers,
        []::VARCHAR[]                                      AS porting,
        []::VARCHAR[]                                      AS supporting
    FROM hc
    LEFT JOIN sd ON sd.steam_appid = hc.app_id
    WHERE hc.app_id NOT IN (SELECT appid FROM linked)
)
SELECT * FROM igdb_games
UNION ALL
SELECT * FROM steam_only
"""


def prepare_seed_parquet(
    *, igdb: str, hushcrasher: str, steam: str, release_dates: str, out_path: str
) -> int:
    """Join the source files and write the prepared parquet. Returns the row count."""
    con = duckdb.connect()
    try:
        for source in (igdb, hushcrasher, steam, release_dates, out_path):
            configure_remote_access(con, source)
        sql = _build_sql(igdb, hushcrasher, steam, release_dates)
        con.execute(f"COPY ({sql}) TO '{out_path}' (FORMAT PARQUET)")
        row = con.execute(f"SELECT count(*) FROM read_parquet('{out_path}')").fetchone()
        return int(row[0]) if row else 0
    finally:
        con.close()

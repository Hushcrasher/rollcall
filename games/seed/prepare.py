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
- steamdb:       steam_appid, name, header_image, short_description
- release_dates: igdb_id, date
"""

import duckdb

from games.seed.pipeline import configure_remote_access


def _build_sql(igdb: str, hushcrasher: str, steamdb: str, release_dates: str) -> str:
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
    SELECT * FROM read_parquet('{steamdb}')
    QUALIFY row_number() OVER (PARTITION BY steam_appid ORDER BY steam_appid) = 1
),
linked AS (
    SELECT DISTINCT steam_app_id AS appid FROM igdb WHERE steam_app_id IS NOT NULL
),
igdb_games AS (
    SELECT
        ig.igdb_id                                                       AS igdb_id,
        ig.steam_app_id                                                  AS steam_appid,
        ig.game_name                                                     AS title,
        COALESCE(fr.release_date, CAST(hc.steam_release_date AS DATE))   AS release_date,
        COALESCE(NULLIF(ig.summary, ''), sd.short_description, '')        AS summary,
        COALESCE(sd.header_image, '')                                     AS cover_url,
        NULL::DOUBLE                                                      AS igdb_rating,
        NULL::DOUBLE                                                      AS igdb_aggregated_rating,
        CAST(hc.review_score AS DOUBLE)                                   AS steam_positive_pct,
        CAST(hc.reviews_steam AS BIGINT)                                  AS steam_review_count,
        COALESCE(hc.genres, []::VARCHAR[])                                AS genres,
        COALESCE(NULLIF(ig.engine_names, []::VARCHAR[]),
                 hc.game_engines, []::VARCHAR[])                          AS engines,
        COALESCE(NULLIF(ig.developer_names, []::VARCHAR[]),
                 hc.developers, []::VARCHAR[])                            AS developers,
        COALESCE(NULLIF(ig.publisher_names, []::VARCHAR[]),
                 hc.publishers, []::VARCHAR[])                            AS publishers,
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
        hc.name                                            AS title,
        CAST(hc.steam_release_date AS DATE)                AS release_date,
        COALESCE(sd.short_description, hc.about_the_game, '') AS summary,
        COALESCE(sd.header_image, '')                      AS cover_url,
        NULL::DOUBLE                                       AS igdb_rating,
        NULL::DOUBLE                                       AS igdb_aggregated_rating,
        CAST(hc.review_score AS DOUBLE)                    AS steam_positive_pct,
        CAST(hc.reviews_steam AS BIGINT)                   AS steam_review_count,
        COALESCE(hc.genres, []::VARCHAR[])                 AS genres,
        COALESCE(hc.game_engines, []::VARCHAR[])           AS engines,
        COALESCE(hc.developers, []::VARCHAR[])             AS developers,
        COALESCE(hc.publishers, []::VARCHAR[])             AS publishers,
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
    *, igdb: str, hushcrasher: str, steamdb: str, release_dates: str, out_path: str
) -> int:
    """Join the source files and write the prepared parquet. Returns the row count."""
    con = duckdb.connect()
    try:
        for source in (igdb, hushcrasher, steamdb, release_dates, out_path):
            configure_remote_access(con, source)
        sql = _build_sql(igdb, hushcrasher, steamdb, release_dates)
        con.execute(f"COPY ({sql}) TO '{out_path}' (FORMAT PARQUET)")
        row = con.execute(f"SELECT count(*) FROM read_parquet('{out_path}')").fetchone()
        return int(row[0]) if row else 0
    finally:
        con.close()

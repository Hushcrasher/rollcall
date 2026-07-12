# No models: search reads other apps' tables. ALL search logic (simple search,
# autocomplete, recruiter search) is isolated in this module so a dedicated
# engine could replace Postgres FTS/pg_trgm later without a rewrite
# (docs/02-ARCHITECTURE.md §2.3).

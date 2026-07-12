"""Games, companies and their reference tables — docs/04-DATABASE-SCHEMA.md §3–6.

Models owned by this app (added in the schema phase, see ROADMAP.md):
Game (§3), Genre, Engine, GameGenre, GameEngine (§4), Company,
CompanyAlias [dormant] (§5), GameCompany (§6).

Rules that shape these models:
- Internal IDs are the pivot; igdb_id / steam_appid / igdb_company_id are
  nullable + unique.
- [source] columns are written ONLY by the seed command (games/management/
  commands/seed_games.py) and are read-only in the app.
- Cover/logo images are never stored by us — URLs to IGDB/Steam CDNs only.
"""

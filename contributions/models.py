"""Contributions — the core table — docs/04-DATABASE-SCHEMA.md §7–9.

Models owned by this app (added in the schema phase, see ROADMAP.md):
Discipline (§7, seeded by data migration), Contribution (§8),
Vouch [dormant, ships empty] (§9).

Rules that shape these models:
- A contribution = (person, game, optional employer company, discipline,
  free-text job title, month/year start, optional month/year end).
- user FK: on delete CASCADE (GDPR). game FK: nullable in schema, required
  in POC forms, PROTECT. company FK: nullable, SET NULL.
- No unique constraint on (user, game): multiple periods/roles are a feature.
- Dates stored as DATE with day=01. CHECK end_date >= start_date.
- status enum (active/disputed/removed) is dormant; only `active` is public.
- Vouch.voter is nullable (anonymized on voter account deletion).
"""

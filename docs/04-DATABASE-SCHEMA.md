# Database Schema — Game Industry Credits Platform (POC)

> Companion docs: `01-DESIGN.md`, `02-ARCHITECTURE.md`, `03-TECH-STACK.md`.
> Notation: types are Postgres-flavored; implement as Django models (BigAutoField PKs assumed, `id` omitted below unless special). `→` = FK.
> **Dormant** = exists in the schema from the initial migration, no UI in POC.

## Conventions & global rules

- **Internal IDs are the pivot everywhere.** External IDs (`igdb_id`, `steam_appid`, `igdb_company_id`) are nullable + unique.
- **Source-owned columns** (marked `[source]`) are imported from the parquet/IGDB, read-only in the app, overwritten on every weekly seed. The seed never touches any other column.
- Timestamps `created_at` / `updated_at` on every table (Django `auto_now_add` / `auto_now`); not repeated below.
- Month/year dates stored as `DATE` with day = 01 (native SQL range/overlap operations).
- Required Postgres extension: `pg_trgm`.

---

## 1. `users`

Extends Django's user (custom user model, email as username — **decide at project start, cannot change later**).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| email | citext/varchar | unique, not null | Login identifier. **Never displayed anywhere.** |
| password | varchar | not null | Django hashing. |
| display_name | varchar(100) | not null | Free: real name or pseudonym. Never require real identity. |
| slug | varchar | unique, not null | Public profile URL. Generated from display_name + suffix on collision. |
| role | varchar enum | not null, default `member` | `member` / `recruiter` / `admin`. |
| email_verified_at | timestamptz | nullable | **Gate: must be non-null to create contributions.** |
| profile_public | boolean | not null, default **true** | False = invisible everywhere (safety valve). |
| contactable | boolean | not null, default **true** | Relay contact allowed. Email itself is never exposed regardless. |
| open_to_work | boolean | not null, default **false** | Badge + recruiter filter. Independent from `contactable`. |
| avatar | varchar | nullable | Key in the S3 bucket. |
| country | varchar(2) | not null, default `''` | ISO 3166-1 alpha-2 (django-countries `CountryField`). Blank = not given. Person-level recruiter-search filter (§3.6); shown on the profile as "City · Country". |
| bio, location, links… | | nullable | Optional profile fields, implementer's discretion. `location` is the free-text **"city / region"** display line (it is *not* nullable in practice: `blank=True, default=''`). |

Indexes: GIN `gin_trgm_ops` on `display_name` (people search). Unique on `email`, `slug`.

**Deletion behavior (GDPR, must work in POC):** hard-delete the row → contributions CASCADE; `vouches.voter_id` SET NULL; `contact_requests` rows: SET NULL on the deleted side (keep the abuse trail anonymized); reports: reporter SET NULL.

## 2. `recruiter_applications`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| user_id | → users | not null, unique(user, status=pending) | Applicant. |
| full_name | varchar | not null | |
| company_name | varchar | not null | Free text (their employer, may not be in `companies`). |
| work_email | varchar | not null | For manual verification. |
| linkedin_url | varchar | nullable | |
| message | text | nullable | |
| status | varchar enum | not null, default `pending` | `pending` / `approved` / `rejected`. |
| reviewed_by | → users | nullable | Admin. |
| reviewed_at | timestamptz | nullable | |

On approval: set `users.role = 'recruiter'`. Managed entirely through Django admin in POC.

## 3. `games`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| igdb_id | integer | nullable, unique | Nullable = door open for future manual games. |
| steam_appid | integer | nullable, unique | |
| title | varchar | not null | `[source]` |
| slug | varchar | unique, not null | Public URL. Platform-generated, stable. |
| release_date | date | nullable | `[source]` |
| parent_game_id | → games | nullable | **Dormant.** Remaster/edition/DLC link (mirrors IGDB parent/version). |
| summary | text | nullable | `[source]` |
| cover_url | varchar | nullable | `[source]` Full URL on IGDB/Steam CDN. **We never store images.** |
| igdb_rating | numeric(5,2) | nullable | `[source]` IGDB user rating. |
| igdb_aggregated_rating | numeric(5,2) | nullable | `[source]` Critics. |
| steam_positive_pct | numeric(5,2) | nullable | `[source]` % positive reviews — powers the "rating > 70%" filter. |
| steam_review_count | integer | nullable | `[source]` Filter noise floor (e.g. ignore % under N reviews). |
| source | varchar enum | not null | `seed` / `igdb_live` / `manual`. Provenance. |
| last_synced_at | timestamptz | nullable | Set by the seed. |

Indexes: GIN `gin_trgm_ops` on `title` (autocomplete). B-tree on `release_date`, `steam_positive_pct`.

## 4. `genres`, `engines` + link tables

Reference tables populated by the seed from IGDB taxonomies. **Model as real M2M link tables, not JSON** — recruiter filters are SQL joins.

`genres`: `igdb_id` (nullable unique), `name` (unique).
`engines`: `igdb_id` (nullable unique), `name` (unique).

`game_genres`: `game_id` → games, `genre_id` → genres, unique together, index on `(genre_id, game_id)`.
`game_engines`: `game_id` → games, `engine_id` → engines, unique together, index on `(engine_id, game_id)`.

> ⚠️ 2D/3D: no direct IGDB field. If implemented, derive best-effort from IGDB keywords/player perspectives in the seed; otherwise defer. Do not block the POC on it.

## 5. `companies`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| igdb_company_id | integer | nullable, unique | |
| name | varchar | not null | `[source]` when seeded. |
| slug | varchar | unique, not null | |
| parent_company_id | → companies | nullable | Flat hierarchy, one level ("Ubisoft Montréal → Ubisoft"). `[source]` |
| logo_url | varchar | nullable | `[source]` from IGDB CDN. Uploaded logos come post-POC with claim. |
| description | text | nullable | Future claim-editable showcase field. |
| claimed_by | → users | nullable | **Dormant.** Future company claim. |
| source | varchar enum | not null | `seed` / `manual`. |

`company_aliases` (**dormant**): `company_id` → companies, `alias` varchar, unique together. GIN trgm index on `alias`. (Also trgm index on `companies.name`.)

## 6. `game_companies` — game ↔ company (from IGDB, NOT user-declared)

The game's official developer/publisher/etc. Distinct from the employer on a contribution. `[source]` entirely.

| Column | Type | Constraints |
|---|---|---|
| game_id | → games | not null |
| company_id | → companies | not null |
| role | varchar enum | not null — `developer` / `publisher` / `porting` / `supporting` |

Unique on `(game_id, company_id, role)`.

## 7. `disciplines`

Fixed reference list, seeded by a data migration (~10–12 rows): Programming, Design, Art, Audio, Production, QA, Writing, Localization, Marketing/Publishing, Business, Support/Other.

| Column | Type | Constraints |
|---|---|---|
| name | varchar | unique, not null |
| sort_order | integer | not null |

Future sub-disciplines = add nullable `parent_id` self-FK (trivial migration).

## 8. `contributions` — the core table

One row = "person X worked on game G, [as an employee of company C], as [job title] ([discipline]), from A to B".

| Column | Type | Constraints | Notes |
|---|---|---|---|
| user_id | → users | not null, **on delete CASCADE** | GDPR: contributions die with the account. |
| game_id | → games | **nullable in schema, required in POC forms**, on delete PROTECT | Nullable keeps the door open for future "unannounced project at company C" (company-only contributions). |
| company_id | → companies | nullable, on delete SET NULL | The person's **employer** for this work (covers outsourcing/freelance). Optional. |
| discipline_id | → disciplines | not null, on delete PROTECT | Powers recruiter filtering. |
| job_title | varchar(150) | not null | Free text, displayed verbatim. |
| start_date | date | not null | Month/year (day=01). |
| end_date | date | nullable | Null = "still working on it". CHECK `end_date >= start_date` when set. |
| status | varchar enum | not null, default `active` | **Dormant.** `active` / `disputed` / `removed`. `disputed` never shown publicly; only `active` rows are displayed/searchable. |

**No unique constraint on (user_id, game_id)** — multiple roles/periods per game are a feature.
App-level CHECK (POC): at least one of `game_id` / `company_id` is non-null (both null forbidden even later).

Indexes: `(user_id)` (profile page), `(game_id)` (game page), composite `(discipline_id, game_id)` (recruiter search), `(company_id)`.

Recruiter search shape (for reference — this query is the product; test it):
```sql
SELECT DISTINCT u.*
FROM users u
JOIN contributions c ON c.user_id = u.id AND c.status = 'active'
JOIN games g          ON g.id = c.game_id
LEFT JOIN game_engines ge ON ge.game_id = g.id
LEFT JOIN game_genres  gg ON gg.game_id = g.id
WHERE u.profile_public
  AND c.discipline_id = :discipline
  AND ge.engine_id = :engine
  AND gg.genre_id  = :genre
  AND g.steam_positive_pct >= :min_rating
  AND (:open_to_work IS NOT TRUE OR u.open_to_work);
```

## 9. `vouches` — **dormant, ships empty**

Peer confirmation of a contribution. Designed now so account deletion and the future trust system need no schema surgery.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| contribution_id | → contributions | not null, on delete CASCADE | |
| voter_id | → users | **nullable**, on delete **SET NULL** | Nullable = anonymization on voter's account deletion (preserves the trust graph of third parties). |
| created_at | timestamptz | not null | |

Unique on `(contribution_id, voter_id)` where voter_id is not null. **Positive-only** (no direction/value column — negative feedback goes through `reports`). Future rule (app-level): voter must have an active contribution on the same game.

## 10. `contact_requests`

Every relay contact. Doubles as rate-limit backend and abuse audit trail.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| sender_id | → users | nullable, on delete SET NULL | Usually a recruiter. |
| recipient_id | → users | nullable, on delete SET NULL | Must have `contactable = true` at send time. |
| subject | varchar | not null | |
| message | text | not null | |
| sent_at | timestamptz | not null | |

Rate limit: count rows per sender per 24h before sending (threshold configurable). Email is sent with Reply-To = sender's email; **recipient's email never appears in any response or page**.

## 11. `reports`

Signal-anything endpoint (contribution, profile, other). Host-status diligence.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| reporter_id | → users | nullable (SET NULL) | Allow anonymous? POC: logged-in only is fine. |
| target_type | varchar enum | not null | `contribution` / `user` / `company` / `game` / `other`. |
| target_id | bigint | nullable | Soft reference (generic FK acceptable). |
| reason | text | not null | |
| status | varchar enum | not null, default `open` | `open` / `resolved` / `dismissed`. |
| handled_by | → users | nullable | Admin, via Django admin. |

## 12. Entity relationship summary

```
users 1──n contributions n──1 games
                │                │
                n──1 companies   ├── n──n genres   (game_genres)
                n──1 disciplines ├── n──n engines  (game_engines)
                                 ├── n──n companies (game_companies, role) [IGDB facts]
                                 └── parent_game_id (self, dormant)
users 1──n vouches n──1 contributions          [dormant]
users 1──n contact_requests (sender/recipient)
users 1──n recruiter_applications
users 1──n reports
companies ── parent_company_id (self) ── 1──n company_aliases [dormant]
```

## 13. Seed write-surface (exhaustive)

The seed command may write ONLY: `games` `[source]` columns + `source`/`last_synced_at`, `genres`, `engines`, `game_genres`, `game_engines`, `companies` `[source]` columns, `game_companies`, `company_aliases` (if source provides alt names). Upsert keys: `igdb_id`, else `steam_appid`, else (`igdb_company_id`) for companies. **It never touches** `users`, `contributions`, `vouches`, `contact_requests`, `reports`, `recruiter_applications`, nor any platform-owned column (slugs, claimed_by, description…). Deletions upstream (game removed from IGDB) do NOT delete locally — games with attached contributions must survive; at most flag `last_synced_at` staleness.

## 14. GDPR data map (quick reference)

| Data | Table | On account deletion | Export (JSON) |
|---|---|---|---|
| Identity, settings | users | Hard delete | Yes |
| Credits | contributions | CASCADE delete | Yes |
| Vouches emitted | vouches.voter_id | SET NULL (anonymize) | Yes (list) |
| Vouches received | vouches | CASCADE with contribution | — |
| Contacts sent/received | contact_requests | SET NULL both directions | Yes |
| Reports filed | reports.reporter_id | SET NULL | No |
| Avatar file | S3 bucket | Delete object | N/A |

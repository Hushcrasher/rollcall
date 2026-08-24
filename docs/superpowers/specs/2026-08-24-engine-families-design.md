# Engine families — design

Date: 2026-08-24 · Surface: the recruiter search's engine facet
(`search/forms.py`, `search/services.py`, `search/views.py`, `games/models.py`)

## 1. Why

A recruiter looking for Unity people has to tick thirteen boxes. The catalogue
spells that one engine as `Unity`, `Unity3D`, `Unity 6`, `Unity 5`, `Unity 4`,
`Unity 3`, and `Unity 2017` through `Unity 2023` — 19,837 game-engine links, or
**36% of the whole catalogue's links**, split across thirteen rows that each look
like a separate engine in the typeahead. Picking `Unity` alone silently misses
`Unity3D`'s 1,003 games.

It is not only versions. `renpy` and `Ren'Py Visual Novel Engine` are the same
engine as `Ren'Py` under two other spellings; `Godot Engine` is `Godot`;
`Game Maker Studio 2` and `GameMaker Studio 2` are one product written twice.
Any rule that only strips version suffixes leaves those behind.

## 2. What a family is

A curated grouping, not a derived one. Measured against the seeded catalogue, a
prefix rule puts **RenderWare** — Electronic Arts', 120 games — inside `Ren'Py`,
and **Crystal Engine**, **Crystal Tools** and **Cryptic Engine** inside
`CryEngine`. Those are not near-misses to be tuned away; they are the rule
working as specified on names that happen to share letters. So the mapping is
written by hand, in code, and reviewed.

The shipped mapping is **20 families over 89 engine names**, covering **76% of
the catalogue's game-engine links**. Every name in it was verified to exist in
the seeded data. The other ~1,200 engines belong to no family and behave exactly
as they do today.

## 3. Data model

A new `EngineFamily` (a unique name; nothing else — the querystring carries pks,
so a slug would be a field with no reader) and a nullable `Engine.family` FK to
it, `on_delete=SET_NULL` because a family is a grouping and dropping one must
never drop the engines.

**`EngineFamily` and `Engine.family` are platform-owned.** `games/seed/upsert.py`
creates `Engine` rows with `model(name=n)` and never updates an existing one
(`_ensure_refs`), so a seeded engine keeps whatever family the platform gave it,
and a newly seeded engine simply arrives unfamilied. This does not widen the
seed's write surface (docs/04 §13) — it adds a column the seed does not know
about.

**Why a separate table rather than a self-FK on `Engine`:** five of the twenty
family heads — `Unreal Engine`, `Adobe Flash`, `id Tech`, `TyranoBuilder`,
`LithTech` — do not exist as engine rows at all; the catalogue carries only their
versions. A self-FK would mean the platform inventing rows inside the
seed-owned `engines` table. The rule that table belongs to the seed is worth
more than the one query parameter this costs.

## 4. Applying the mapping

The mapping lives in `games/engine_families.py` as `FAMILIES: dict[str,
list[str]]`, and a `link_engine_families` management command applies it.

**A command, not a data migration.** The rows it edits exist only after
`seed_games` has run, so a migration would execute against an empty table on a
fresh clone and do nothing. The command is idempotent — it upserts the family
rows, sets `Engine.family` for every name it recognises, clears it for engines
no longer listed, and reports names in the mapping that matched nothing, which
is how a typo in the mapping surfaces.

It joins `seed_games` in the deploy and dev-setup sequence.

## 5. The filter

`RecruiterSearchForm` gains `engine_families`, a second
`ModelMultipleChoiceField` posting `?engine_families=3` beside the existing
`?engines=9`. Both feed one visual field — the recruiter sees a single
**Game engine** box.

`recruiter_search()` gains `engine_family_ids`. In `_matching_credits` the two
are **OR'd together within the facet**, matching how every other multi-value
facet behaves:

```python
if engine_ids or engine_family_ids:
    credits = credits.filter(
        Q(game__engines__in=list(engine_ids))
        | Q(game__engines__family_id__in=list(engine_family_ids))
    )
```

So "Unity **or** Godot 4" is one filter, and "Unity" reaches all thirteen
spellings without the recruiter naming them.

The `.distinct()` in `_assemble_results` already covers the fan-out this can
produce, exactly as it does for the existing `game__engines__in`.

## 6. The typeahead

One box, one endpoint, a mixed list. Typing `unity` returns the family head
first and its matching members indented beneath it:

```
Unity                     ← picks the whole family
    Unity 2021            ← picks that version only
    Unity 2022
```

Each option carries the parameter it posts to — `data-param="engine_families"`
for a head, `data-param="engines"` for a member — because a chip's hidden input
has to be named for the field that will clean it. The page's `addChip` reads
that attribute and clones the matching `<template>`; without it there would be
no way to tell the two kinds of chip apart client-side.

An engine with no family renders unindented and posts to `engines`, unchanged.

Families are matched on their own name, and a head is also shown when a *member*
matches — typing `2021` should still offer the Unity family, not only the bare
version, since that is the pick the recruiter most likely wants.

## 7. Tests

- The mapping's integrity: every family name is unique, no engine name appears
  in two families, and the file parses into the shape the command expects.
- `link_engine_families` is idempotent, clears a family when a name is removed
  from the mapping, and reports unmatched names.
- `recruiter_search(engine_family_ids=[unity])` finds people credited on games
  tagged `Unity 2021` — the whole point — and does not find people on an
  unrelated engine.
- A family and a loose engine submitted together OR within the facet.
- The typeahead returns the head before its members, tags each option with its
  parameter, and offers the head when only a member matches.
- A crafted `?engine_families=abc` renders the page rather than raising.

## 8. Out of scope

**Merging the engine shares shown on result cards** (`Unity 67% · Unity 6 33%`
should read `Unity 100%`). It depends on this mapping and is part of the results
table change that follows.

Company dedup, which is the same class of problem for a different table, stays
where it is in ROADMAP's follow-ups.

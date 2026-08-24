# Search results as a table — design

Date: 2026-08-24 · Surface: the home page's results section
(`templates/search/people_search.html`, `search/services.py`)

## 1. Why

A recruiter's job on this page is to **compare people**, and the results were a
stack of cards — a shape that reads one person at a time and makes comparing two
of them a scroll and a memory exercise. Each card also spent a lot of vertical
room on prose (`1 credit · 1 game · 2020–2021`) that is really four values.

A table puts the same facts in columns, so the eye runs down one attribute
across everybody.

## 2. Columns

| Column | Contents |
|---|---|
| **Name** | Profile link, with the `Open to work` badge beside it |
| **Based in** | `City · Country`, or `—` |
| **Experience** | Up to three matching credits, then a `+N more` link |
| **Credits** | Career total |
| **Games** | Career total, distinct |
| **In the industry** | `2010–2025`, or `2010–present` |
| **Engines on credited games** | `Unity 100%` |

Decisions taken with the owner:

- **The span, not a duration.** `2010–2025` rather than `15 years`: it says when
  as well as how long, and the reader can subtract.
- **`Open to work` stays with the name** rather than taking a column — it is a
  strong signal for a recruiter and costs nothing there.
- **Location gets its own column.** It is a filter, so it should be a column the
  eye can scan; under the name it would only be findable per row.
- **Experience stays capped at three** with `+N more` — now a **link to the
  profile**, where the whole career lives. A veteran with 200 credits would
  otherwise make one row taller than a screen.
- **An experience line reads `dates: role (discipline) at game`.** Dates lead
  because that is the axis a reader scans a career on.

## 3. The engine column merges by family

`Unity 67% · Unity 6 33%` said nothing true about anybody — it is one engine
under two of its names. Shares are now counted by **family** where one exists
(spec `2026-08-24-engine-families`), so that career reads `Unity 100%`.

The SQL `.distinct()` dedupes `(user, game, engine)`, which is not enough once
several engines collapse into one family: a game tagged with two Unity spellings
would count twice toward Unity. The family key is deduped again in Python.

**The column header is load-bearing.** A bare percentage beside a person reads
as a score *of them*, which non-negotiable #7 exists to prevent. `Engines on
credited games` names what the number measures — their games, not them. It is
the same guard the old card carried in its inline label, moved to where a table
puts labels.

## 4. Drawing

No column rules; row rules only, at `--pico-muted-border-color`. The grid should
sit under the data rather than draw a box around every value. Pico rules both
axes by default, so both are reset and only `border-bottom` is put back.

The table lives in an `overflow-x: auto` wrapper: seven columns must scroll
inside their own box and never push the page sideways.

## 5. Narrow screens

Below 768px the table stops being a table — `thead` is hidden, every cell
becomes a block, and each one reinstates its own header from a `data-label`
attribute via `::before`. A row becomes a labelled block separated from the next
by the same faint rule.

Horizontal scrolling was considered and rejected: reading one person would mean
dragging, on the surface most likely to be opened from a phone.

`data-label` is therefore not decoration — a cell without one is a value with no
meaning on a phone, and no CSS test can catch that. A test asserts every cell
carries one.

## 6. Tests

- The seven headers, and that every body cell carries a `data-label`.
- The scroll wrapper exists.
- An experience line's shape, and that `+N more` is a link to the profile.
- A person with no location renders `—`, not an empty cell.
- No results renders the sentence and **no** empty table.
- Engine shares merge by family, and a game tagged with two spellings of one
  family counts once.

The two card tests that asserted the old combined stats line are rewritten per
cell. One property they guarded is genuinely gone: the `{% blocktranslate count %}`
plural branch on `1 credit` / `2 credits`. A count column is a bare number under
a header and has no singular — that is the point of a column.

## 7. Out of scope

The profile page's own credit list, which has its own layout and is not a
comparison surface.

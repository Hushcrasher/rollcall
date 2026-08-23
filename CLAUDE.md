# Rollcall — instructions for coding agents

Rollcall is a credits database for the game industry (Django monolith,
server-rendered + htmx, Postgres). The docs are load-bearing: behavior is
specified in `docs/`, and code that contradicts them is a bug even if it works.

## Read before changing anything

1. `docs/00-README.md` — the **ten non-negotiables**. If in doubt, these win.
2. `docs/01-DESIGN.md` — source of truth for behavior.
3. The relevant design record in `docs/superpowers/specs/` for any recent
   surface you touch (home page, declare funnel, people search, profile split,
   GitHub block, Redis rate limit). **Specs are binding; the files in
   `docs/superpowers/plans/` are historical execution logs — ignore them.**

## Hard rules an agent must never break

- **Never expose the account email** in any page, response, header, export-to-others or
  log. A member's opt-in `public_email` renders on their public profile page only —
  nowhere else (spec 2026-08-21-public-contact-email). Contact is otherwise
  relay-only (`contact/views.py`, Reply-To pattern). `User.__str__` returns
  `display_name` — keep it that way.
- **No public negative signals**: no down-votes, no "disputed" labels, no
  numeric scores of people. Only `status='active'` credits render anywhere.
- **Every user-facing string goes through i18n** (`gettext` /
  `{% translate %}`), including form labels, messages, emails, inline-JS text.
- **The seed's write-surface is closed** (docs/04 §13): the seed writes only
  `[source]` columns and seed-owned link tables; it never deletes local games
  and never touches platform-owned columns. `games/seed/upsert.py` enforces
  this — don't widen it.
- **No application code reads the parquet** — only the seed commands do.
- **Email verification gates** credit creation *and* the contact relay
  (`accounts/mixins.py`). The declare funnel's `pending` rows are the one
  documented relaxation (docs/00 #6, docs/01 §3.3).
- **Emails are stored lowercase** with a `Lower(email)` unique constraint —
  keep every new write path case-folding.
- Secrets only in env vars (`.env.example` is the canonical list); the private
  parquets under `data/` never enter git or Docker images.

## Toolchain (all must pass — CI runs exactly these)

```bash
docker compose up db        # Postgres 16 (the only service tests need)
uv run pytest               # ~430 tests, ~5s; no network, no Redis
uv run ruff check . && uv run ruff format --check .
uv run ty check             # fully-typed Python: annotate everything
docker build .              # the image must build from a fresh clone
```

- **TDD is the house style**: write the failing test first. The seed dedup,
  the people-search query, and account deletion are non-negotiable test zones
  (docs/02 §7) — changes there without tests will not merge.
- `ty` has no Django plugin: use the existing small accommodations
  (`# ty: ignore[...]`, `Any`-bridges) rather than inventing new patterns.
- Search logic lives ONLY in `search/services.py`.

## Process

- **Never commit to `main` directly — branch first, then open a PR.** Start the
  branch (`feat/…`, `docs/…`, `fix/…`) *before* the first commit; the owner
  merges. `main` carries a protection ruleset (PR required, 4 status checks),
  but an owner-authenticated push can bypass it and GitHub only says so
  afterwards — so nothing will stop you, and the checks simply never run.
  Retrofitting a branch after committing to `main` is far messier than
  branching up front.
- Commits are DCO signed-off (`git commit -s`) — CI rejects unsigned PR commits.
- A behavior change updates `docs/01-DESIGN.md` + `ROADMAP.md` in the same PR;
  substantial features get a design record in `docs/superpowers/specs/`.
- Match the codebase's comment style: comments state constraints and reasons
  ("why"), never narration of what the next line does.

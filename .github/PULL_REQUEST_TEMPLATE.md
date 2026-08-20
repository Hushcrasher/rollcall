## What & why

<!-- One paragraph: the behavior change and the reason. Link the issue. -->

## Checklist

The CI enforces most of these, but running them locally is faster:

- [ ] `uv run pytest` passes — new behavior comes **with tests, written first**
      (the seed dedup, people-search query, and account deletion are
      non-negotiable test zones — docs/02-ARCHITECTURE.md §7)
- [ ] `uv run ruff check . && uv run ruff format --check .` passes
- [ ] `uv run ty check` passes — every function/method/fixture is annotated
- [ ] Every commit is signed off (`git commit -s`) — the DCO check fails otherwise
- [ ] All user-facing strings go through i18n (`{% translate %}` / `gettext`)
- [ ] No personal email can reach any page, response, header or export;
      no public negative signals (docs/00-README.md — the non-negotiables)
- [ ] If behavior changed: `docs/01-DESIGN.md` and `ROADMAP.md` updated in
      this same PR

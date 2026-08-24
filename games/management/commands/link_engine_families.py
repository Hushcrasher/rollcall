"""Apply `games/engine_families.py` to the Engine table.

A command rather than a data migration: the rows it edits exist only after
`seed_games` has run, so a migration would execute against an empty table on a
fresh clone and quietly do nothing. Run it after every seed.
"""

from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from games.engine_families import FAMILIES
from games.models import Engine, EngineFamily


class Command(BaseCommand):
    help = "Group engine rows into curated families (games/engine_families.py)."

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        families = {name: EngineFamily.objects.get_or_create(name=name)[0] for name in FAMILIES}

        # Name -> family, flattened once. The mapping is small enough that the
        # whole Engine name index fits in memory comfortably.
        wanted: dict[str, EngineFamily] = {
            engine_name: families[family_name]
            for family_name, engine_names in FAMILIES.items()
            for engine_name in engine_names
        }

        rows = list(Engine.objects.filter(name__in=wanted).only("id", "name", "family_id"))
        changed = [e for e in rows if e.family_id != wanted[e.name].pk]
        for engine in changed:
            engine.family = wanted[engine.name]
        Engine.objects.bulk_update(changed, ["family"], batch_size=1000)

        # An engine dropped from the mapping must lose its family, or a rename
        # would leave the old grouping in place with nothing pointing at it.
        orphaned = Engine.objects.exclude(name__in=wanted).exclude(family__isnull=True)
        cleared = orphaned.update(family=None)

        # A name that matches nothing is how a typo in the mapping surfaces —
        # silently skipping it is what let it be wrong in the first place.
        unmatched = sorted(set(wanted) - {e.name for e in rows})

        empty = EngineFamily.objects.filter(engines__isnull=True).values_list("name", flat=True)

        self.stdout.write(
            f"{len(families)} families · {len(rows)} engines matched "
            f"({len(changed)} re-linked, {cleared} cleared)"
        )
        if unmatched:
            self.stdout.write(
                self.style.WARNING(f"{len(unmatched)} mapped names not in the catalogue:")
            )
            for name in unmatched:
                self.stdout.write(f"  {name}")
        if empty:
            self.stdout.write(self.style.WARNING(f"families with no engine: {', '.join(empty)}"))

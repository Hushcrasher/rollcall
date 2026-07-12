"""Data migration — the fixed discipline list (docs/04-DATABASE-SCHEMA.md §7).

Inspired by IGDA credit standards; the person picks their own discipline.
Renames/additions later are ordinary data migrations.
"""

from django.db import migrations

DISCIPLINES = [
    "Programming",
    "Design",
    "Art",
    "Audio",
    "Production",
    "QA",
    "Writing",
    "Localization",
    "Marketing/Publishing",
    "Business",
    "Support/Other",
]


def seed_disciplines(apps, schema_editor):
    Discipline = apps.get_model("contributions", "Discipline")
    for position, name in enumerate(DISCIPLINES, start=1):
        Discipline.objects.get_or_create(name=name, defaults={"sort_order": position * 10})


def unseed_disciplines(apps, schema_editor):
    Discipline = apps.get_model("contributions", "Discipline")
    Discipline.objects.filter(name__in=DISCIPLINES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("contributions", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_disciplines, unseed_disciplines),
    ]

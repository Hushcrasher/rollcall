"""The curated engine mapping and the command that applies it
(spec 2026-08-24-engine-families).

The mapping is hand-written data, so these tests guard the two ways hand-written
data goes wrong: a name landing in two families, and a name that has silently
stopped matching anything in the catalogue.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from games.engine_families import FAMILIES
from games.models import Engine, EngineFamily

pytestmark = pytest.mark.django_db


def _run() -> str:
    out = StringIO()
    call_command("link_engine_families", stdout=out)
    return out.getvalue()


# --- the mapping itself (no database needed, but cheap to keep here) --------


def test_no_engine_name_belongs_to_two_families() -> None:
    """The command builds a name -> family dict, so a duplicate would not raise
    — the later family would just silently win. This is the only place that
    catches it."""
    seen: dict[str, str] = {}
    for family, names in FAMILIES.items():
        for name in names:
            assert name not in seen, f"{name!r} is in both {seen[name]!r} and {family!r}"
            seen[name] = family


def test_family_names_are_not_also_member_names_of_another_family() -> None:
    """A family head that is also somebody else's member would make the two
    impossible to tell apart in the typeahead."""
    members = {name for names in FAMILIES.values() for name in names}
    for family in FAMILIES:
        assert family not in members or family in FAMILIES[family], family


# --- the command -----------------------------------------------------------


def test_links_engines_to_their_family() -> None:
    Engine.objects.create(name="Unity")
    Engine.objects.create(name="Unity 2021")
    Engine.objects.create(name="Unity3D")

    _run()

    unity = EngineFamily.objects.get(name="Unity")
    assert set(unity.engines.values_list("name", flat=True)) == {
        "Unity",
        "Unity 2021",
        "Unity3D",
    }


def test_an_unmapped_engine_keeps_no_family() -> None:
    """~1,200 engines belong to no family and must go on behaving as they did."""
    Engine.objects.create(name="Insomniac Engine v.4.0")

    _run()

    assert Engine.objects.get(name="Insomniac Engine v.4.0").family is None


def test_running_twice_changes_nothing() -> None:
    """It runs after every seed, so a second run must be a no-op rather than
    re-linking (or duplicating) what the first one did."""
    Engine.objects.create(name="Godot Engine")
    _run()
    before = EngineFamily.objects.count()

    second = _run()

    assert EngineFamily.objects.count() == before
    assert "0 re-linked" in second


def test_an_engine_dropped_from_the_mapping_loses_its_family() -> None:
    """Otherwise a rename would leave the old grouping in place, still matching
    filters, with nothing in the mapping pointing at it."""
    engine = Engine.objects.create(name="Godot Engine")
    _run()
    assert Engine.objects.get(pk=engine.pk).family is not None

    engine.name = "Some Other Engine"
    engine.save(update_fields=["name"])
    _run()

    assert Engine.objects.get(pk=engine.pk).family is None


def test_a_mapped_name_absent_from_the_catalogue_is_reported() -> None:
    """A typo in the mapping matches nothing and would otherwise be invisible —
    the filter would just quietly cover one spelling fewer."""
    Engine.objects.create(name="Unity")

    output = _run()

    assert "not in the catalogue" in output
    assert "Unity 2021" in output  # mapped, but no such row in this test's db


def test_reports_families_left_with_no_engine() -> None:
    """An empty family would sit in the typeahead offering a filter that cannot
    match anything."""
    output = _run()  # nothing seeded at all

    assert "families with no engine" in output

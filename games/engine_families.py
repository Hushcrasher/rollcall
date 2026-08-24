"""Curated engine families (spec 2026-08-24-engine-families).

The catalogue spells one engine many ways. `Unity` alone arrives as thirteen
rows — versions (`Unity 2021`) and alternative spellings (`Unity3D`) side by
side — which made a recruiter tick thirteen boxes to ask one question.

**Curated, not derived, and deliberately so.** Measured against the seeded
catalogue, a "same prefix" rule files RenderWare (Electronic Arts', 120 games)
under Ren'Py, and Crystal Engine, Crystal Tools and Cryptic Engine under
CryEngine. Those are not near-misses to tune away — they are what the rule
does to names that share letters. Every name below was checked to exist in the
seeded data; `link_engine_families` reports any that stops matching, which is
how a typo here surfaces.

Engines absent from this file belong to no family and behave as they always
have. Coverage is ~76% of the catalogue's game-engine links; the tail is ~1,200
engines with a handful of games each, where grouping buys nothing.
"""

# Ordered most-used family first, purely so a reader sees the weight at a glance.
FAMILIES: dict[str, list[str]] = {
    "Unity": [
        "Unity",
        "Unity3D",
        "Unity 3",
        "Unity 4",
        "Unity 5",
        "Unity 6",
        "Unity 2017",
        "Unity 2018",
        "Unity 2019",
        "Unity 2020",
        "Unity 2021",
        "Unity 2022",
        "Unity 2023",
    ],
    "Unreal Engine": [
        "Unreal",
        "Unreal Engine 1",
        "Unreal Engine 2",
        "Unreal Engine 2.5",
        "Unreal Engine 3",
        "Unreal Engine 4",
        "Unreal Engine 5",
    ],
    "RPG Maker": [
        "RPG Maker",
        "Rpgmaker",
        "RPG Maker 95",
        "RPG Maker 2000",
        "RPG Maker 2003",
        "RPG Maker XP",
        "RPG Maker VX",
        "RPG Maker VX Ace",
        "RPG Maker MV",
        "RPG Maker MZ",
        "RPG Maker Fes",
        "RPG Maker Dante 98 II",
    ],
    "GameMaker": [
        "GameMaker",
        "GameMaker Studio",
        "GameMaker Studio 2",
        "GameMaker: Studio",
        "Game Maker",
        "Game Maker Studio",
        "Game Maker Studio 2",
    ],
    "Godot": ["Godot", "Godot Engine"],
    # NOT RenderWare, RenJS, RENA, RenderDragon or RENKEI Engine — unrelated
    # engines a prefix rule would have swept in here.
    "Ren'Py": ["Ren'Py", "renpy", "Ren'Py Visual Novel Engine"],
    # Flashpunk is a separate framework and stays out.
    "Adobe Flash": ["Adobe Flash Player", "Flash", "Flash CS6"],
    # Multimedia Fusion is the same product under its pre-rename name.
    "Clickteam Fusion": ["Clickteam Fusion", "Multimedia Fusion"],
    "HTML5": ["HTML5", "HTML"],
    "Construct": ["Construct", "Construct 2", "Construct 3"],
    "Source": ["Source", "Source 2"],
    "id Tech": [
        "id Tech 1",
        "id Tech 2",
        "id Tech 3",
        "id Tech 4",
        "id Tech 5",
        "id Tech 6",
        "id Tech 7",
        "id Tech 8",
    ],
    "TyranoBuilder": [
        "TyranoScript",
        "TyranoBuilder Engine",
        "Tyranobuilder Visual Novel Studio",
    ],
    # NOT Crystal Engine, Crystal Tools or Cryptic Engine.
    "CryEngine": ["CryEngine", "Cryengine 2", "CryEngine 3", "CryEngine 5"],
    "Cocos2d": ["Cocos2d", "Cocos2d-x"],
    "Frostbite": ["Frostbite", "Frostbite 2", "Frostbite 3"],
    "GDevelop": ["GDevelop", "GDevelop 5"],
    "libGDX": ["libgdx", "libGDX"],
    "LithTech": [
        "LithTech 1",
        "LithTech 2.x",
        "LithTech 6",
        "LithTech V5",
        "LithTech Jupiter",
        "LithTech Jupiter EX",
        "LithTech Talon",
    ],
    "Microsoft XNA": ["Microsoft XNA", "XNA Game Studio"],
}

"""Generate deterministic starter adventure hooks from a fixed template pool."""

from typing import List

from models import AdventureHook, Character


# Fixed seeds keep early-game QA stable while still rotating by party makeup.
ADVENTURE_TEMPLATES = [
    {
        "title": "Ashes Under Blackbarrow",
        "summary": "A mining village has gone silent after smoke began rising from sealed burial tunnels beneath the old barrow.",
        "tone": "grim",
        "difficulty": "medium",
        "opening_scene": "The party arrives in a rain-soaked frontier village where every chimney is cold except one."
    },
    {
        "title": "The Lantern Road Debt",
        "summary": "A merchant house offers coin for escort duty, but the road is lined with missing caravans and unpaid ghosts.",
        "tone": "dark fantasy",
        "difficulty": "easy",
        "opening_scene": "A tired factor spreads a blood-stained ledger across the tavern table and names a road nobody wants to travel."
    },
    {
        "title": "The Broken Chapel Bell",
        "summary": "A ruined hillside shrine rings on moonless nights, and each toll is followed by another villager vanishing.",
        "tone": "horror",
        "difficulty": "medium",
        "opening_scene": "The bell sounds once across the valley while the priest insists the chapel has no rope and no living keeper."
    },
    {
        "title": "Knives at Lowwater Market",
        "summary": "A riverside market town is rotting under extortion, sabotage, and a feud between hired blades and desperate guilders.",
        "tone": "street-level",
        "difficulty": "medium",
        "opening_scene": "The fish market is still open when the first body drops onto the counting tables."
    },
]


def generate_initial_adventures(characters: List[Character]) -> List[AdventureHook]:
    # Rotate the template list so different parties do not always see the same first option.
    party_seed = sum(len(character.name) + character.level for character in characters) if characters else 0
    rotated = ADVENTURE_TEMPLATES[party_seed % len(ADVENTURE_TEMPLATES) :] + ADVENTURE_TEMPLATES[: party_seed % len(ADVENTURE_TEMPLATES)]

    hooks: List[AdventureHook] = []
    for template in rotated[:3]:
        hooks.append(AdventureHook(**template))
    return hooks

"""Import 2024 (XPHB) character-creation options from a local 5e.tools checkout.

The project ships a hand-written builder catalog at
``backend/data/character_builder_2024.json``. It only covered 4 species,
7 backgrounds and 10 origin feats, which forced the Setup agent to work from a
much smaller option space than the rules actually offer.

This script merges the missing XPHB entries in from a local 5e.tools source tree
(https://github.com/5etools-mirror-3/5etools-src). It is additive and
idempotent: entries already present in the catalog are never rewritten, so
hand-tuned data and anything the frontend or tests depend on stays stable.

Only mechanical fields are imported - names, speeds, trait names, skill
proficiencies, ability-score options and origin feat references. No prose,
descriptions or rendered content are copied.

Usage:

    python utils/import_5etools_builder_options.py --source "E:/5e Tools/data" --dry-run
    python utils/import_5etools_builder_options.py --source "E:/5e Tools/data"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from rules_catalog import ABILITY_ALIAS, SKILL_TO_ABILITY  # noqa: E402

CATALOG_PATH = os.path.join(BACKEND_ROOT, "data", "character_builder_2024.json")
SOURCE_EDITION = "XPHB"
ORIGIN_FEAT_CATEGORY = "O"

# 5e.tools 用 "magic initiate; cleric|xphb" 这类键引用专长；我们的目录用
# "Magic Initiate (Cleric)" 这种显示名，两边必须一一对上，
# 否则 validate_character 会因为背景的 origin_feat 找不到而报错。
FEAT_KEY_PATTERN = re.compile(r"^(?P<name>[^|;]+)(?:;\s*(?P<variant>[^|]+))?(?:\|.*)?$")

SKILL_LOOKUP: Dict[str, str] = {name.lower(): name for name in SKILL_TO_ABILITY}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    return slug or "entry"


def title_case_words(value: str) -> str:
    return " ".join(word[:1].upper() + word[1:] for word in str(value).split())


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_feat_reference(raw_key: str) -> str:
    """Turn ``magic initiate; cleric|xphb`` into ``Magic Initiate (Cleric)``."""

    match = FEAT_KEY_PATTERN.match(str(raw_key).strip())
    if not match:
        return title_case_words(raw_key)
    name = title_case_words(match.group("name").strip())
    variant = match.group("variant")
    if variant:
        return f"{name} ({title_case_words(variant.strip())})"
    return name


def normalize_skill(raw_skill: str) -> Optional[str]:
    return SKILL_LOOKUP.get(str(raw_skill).strip().lower())


def normalize_speed(raw_speed: Any) -> int:
    if isinstance(raw_speed, dict):
        walk = raw_speed.get("walk", 30)
        return int(walk) if isinstance(walk, (int, float)) else 30
    if isinstance(raw_speed, (int, float)):
        return int(raw_speed)
    return 30


def extract_species(races: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    extracted: List[Dict[str, Any]] = []
    for entry in races:
        if entry.get("source") != SOURCE_EDITION or entry.get("_copy"):
            continue
        traits = [
            str(item["name"]).strip()
            for item in entry.get("entries", [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        extracted.append(
            {
                "id": slugify(entry["name"]),
                "name": str(entry["name"]).strip(),
                "speed": normalize_speed(entry.get("speed")),
                "traits": traits,
            }
        )
    return extracted


def extract_ability_options(raw_ability: Any) -> Tuple[Dict[str, int], List[str]]:
    """Return a concrete default +2/+1 split plus the abilities it may be chosen from.

    2024 backgrounds let the player distribute the increases, but the catalog
    schema stores a single fixed mapping. Keep the fixed default for existing
    consumers and expose the legal choices alongside it.
    """

    choices: List[str] = []
    for block in raw_ability or []:
        if not isinstance(block, dict):
            continue
        weighted = (block.get("choose") or {}).get("weighted") or {}
        for short_name in weighted.get("from", []):
            full_name = ABILITY_ALIAS.get(str(short_name).strip())
            if full_name and full_name not in choices:
                choices.append(full_name)

    bonuses: Dict[str, int] = {}
    if len(choices) >= 2:
        bonuses = {choices[0]: 2, choices[1]: 1}
    return bonuses, choices


def extract_backgrounds(backgrounds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    extracted: List[Dict[str, Any]] = []
    for entry in backgrounds:
        if entry.get("source") != SOURCE_EDITION or entry.get("_copy"):
            continue

        skills: List[str] = []
        for block in entry.get("skillProficiencies", []):
            if not isinstance(block, dict):
                continue
            for raw_skill, enabled in block.items():
                if not enabled:
                    continue
                normalized = normalize_skill(raw_skill)
                if normalized and normalized not in skills:
                    skills.append(normalized)

        origin_feat = ""
        for block in entry.get("feats", []):
            if not isinstance(block, dict):
                continue
            for raw_key, enabled in block.items():
                if enabled:
                    origin_feat = normalize_feat_reference(raw_key)
                    break
            if origin_feat:
                break

        bonuses, options = extract_ability_options(entry.get("ability"))
        extracted.append(
            {
                "id": slugify(entry["name"]),
                "name": str(entry["name"]).strip(),
                "ability_bonuses": bonuses,
                "ability_options": options,
                "origin_feat": origin_feat,
                "skill_proficiencies": skills,
            }
        )
    return extracted


def extract_origin_feats(feats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    extracted: List[Dict[str, Any]] = []
    for entry in feats:
        if entry.get("source") != SOURCE_EDITION or entry.get("_copy"):
            continue
        if entry.get("category") != ORIGIN_FEAT_CATEGORY:
            continue
        name = str(entry["name"]).strip()
        extracted.append({"id": slugify(name), "name": name})
    return extracted


def merge_section(
    existing: List[Dict[str, Any]],
    incoming: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Append entries whose name is not already present; never rewrite existing ones."""

    known = {str(item.get("name") or "").strip().lower() for item in existing}
    merged = list(existing)
    added: List[str] = []
    for item in incoming:
        key = str(item.get("name") or "").strip().lower()
        if not key or key in known:
            continue
        known.add(key)
        merged.append(item)
        added.append(str(item["name"]))
    return merged, added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source",
        default=os.environ.get("FIVE_E_TOOLS_DATA", r"E:\5e Tools\data"),
        help="Path to the 5e.tools data directory.",
    )
    parser.add_argument("--catalog", default=CATALOG_PATH, help="Target builder catalog JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Report the merge without writing.")
    args = parser.parse_args()

    required = ["races.json", "backgrounds.json", "feats.json"]
    missing = [name for name in required if not os.path.isfile(os.path.join(args.source, name))]
    if missing:
        parser.error(f"Source directory is missing {', '.join(missing)}: {args.source}")

    catalog = load_json(args.catalog)
    races = load_json(os.path.join(args.source, "races.json")).get("race", [])
    backgrounds = load_json(os.path.join(args.source, "backgrounds.json")).get("background", [])
    feats = load_json(os.path.join(args.source, "feats.json")).get("feat", [])

    catalog["species"], added_species = merge_section(catalog.get("species", []), extract_species(races))
    catalog["backgrounds"], added_backgrounds = merge_section(
        catalog.get("backgrounds", []), extract_backgrounds(backgrounds)
    )
    catalog["origin_feats"], added_feats = merge_section(
        catalog.get("origin_feats", []), extract_origin_feats(feats)
    )

    # 背景引用的起源专长必须存在，否则 validate_character 会拒绝用该背景建出的角色。
    feat_names = {str(item.get("name") or "") for item in catalog["origin_feats"]}
    dangling = sorted(
        {
            str(item.get("origin_feat") or "")
            for item in catalog["backgrounds"]
            if item.get("origin_feat") and item["origin_feat"] not in feat_names
        }
    )

    print(f"species     +{len(added_species):<3} {added_species}")
    print(f"backgrounds +{len(added_backgrounds):<3} {added_backgrounds}")
    print(f"origin_feats+{len(added_feats):<3} {added_feats}")
    print(f"totals: species={len(catalog['species'])} backgrounds={len(catalog['backgrounds'])} origin_feats={len(catalog['origin_feats'])}")
    if dangling:
        print(f"ERROR: backgrounds reference unknown origin feats: {dangling}")
        return 1

    if args.dry_run:
        print("dry-run: catalog not written")
        return 0

    with open(args.catalog, "w", encoding="utf-8") as handle:
        json.dump(catalog, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"written: {args.catalog}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

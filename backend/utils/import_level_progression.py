"""从本地5e.tools的2024职业数据提取建卡数值与条目名称，不复制规则正文。"""
import argparse
import json
from pathlib import Path
import re


def clean(value):
    if isinstance(value, str):
        return re.sub(r"\{@\w+ ([^}|]+)(?:\|[^}]+)?\}", r"\1", value)
    if isinstance(value, dict):
        if value.get("type") == "dice":
            return "+".join(f"{roll['number']}d{roll['faces']}" for roll in value.get("toRoll", []))
        return value.get("value", "")
    return value


def features(refs, subclass=False):
    result = []
    for ref in refs:
        text = ref if isinstance(ref, str) else ref.get("subclassFeature" if subclass else "classFeature", "")
        parts = text.split("|")
        index = 5 if subclass else 3
        if len(parts) > index and parts[index].isdigit():
            result.append({"name": parts[0], "level": int(parts[index]), "source": "XPHB"})
    return result


def extract(value, subclass=False):
    tables = value.get("subclassTableGroups" if subclass else "classTableGroups", [])
    slots = next((table["rowsSpellProgression"] for table in tables if "rowsSpellProgression" in table), [])
    metrics = [{} for _ in range(20)]
    for table in tables:
        for index, row in enumerate(table.get("rows", [])[:20]):
            for label, cell in zip(table.get("colLabels", []), row):
                metrics[index][clean(label)] = clean(cell)
    return {
        "name": value["name"], "source": value["source"],
        "spellcasting_ability": value.get("spellcastingAbility", "").upper(),
        "caster_progression": value.get("casterProgression", ""),
        "cantrips": value.get("cantripProgression", [0] * 20),
        "prepared": value.get("preparedSpellsProgression", [0] * 20),
        "slots": slots, "metrics": metrics,
        "features": features(value.get("subclassFeatures" if subclass else "classFeatures", []), subclass),
        "additional_spells": value.get("additionalSpells", []),
        "arcanum": value.get("spellsKnownProgressionFixedByLevel", {}),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data/level_progression_2024.json")
    args = parser.parse_args()
    builder = json.loads((Path(__file__).resolve().parents[1] / "data/character_builder_2024.json").read_text(encoding="utf-8"))
    result = {"source": "5e.tools XPHB (2024), numeric progression and feature references", "classes": {}}
    for base in builder["classes"]:
        data = json.loads((args.source / f"class-{base['name'].lower()}.json").read_text(encoding="utf-8"))
        value = next(item for item in data["class"] if item["source"] == "XPHB")
        entry = extract(value)
        entry["hit_die"] = value["hd"]["faces"]
        entry["subclasses"] = [
            {**extract(sub, True), "id": re.sub(r"[^a-z0-9]+", "-", sub["name"].lower()).strip("-")}
            for sub in data.get("subclass", []) if sub.get("source") == "XPHB" and sub.get("classSource") == "XPHB"
        ]
        result["classes"][base["name"]] = entry
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(result['classes'])} class progressions to {args.output}")


if __name__ == "__main__":
    main()

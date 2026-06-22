"""Generate local monster templates from the bundled D&D markdown notes.

The source documents and generated monster JSON files are local-only assets
ignored by git. This script keeps the extraction reproducible without checking
rules text into the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from models import MonsterTemplate, Stats  # noqa: E402
from storage import safe_file_stem  # noqa: E402


ABILITY_COLUMNS = [
    ("力量", "strength"),
    ("敏捷", "dexterity"),
    ("体质", "constitution"),
    ("智力", "intelligence"),
    ("感知", "wisdom"),
    ("魅力", "charisma"),
]

SKILL_NAME_MAP = {
    "运动": "athletics",
    "体操": "acrobatics",
    "巧手": "sleight_of_hand",
    "隐匿": "stealth",
    "奥秘": "arcana",
    "历史": "history",
    "调查": "investigation",
    "自然": "nature",
    "宗教": "religion",
    "驯兽": "animal_handling",
    "洞悉": "insight",
    "医药": "medicine",
    "察觉": "perception",
    "求生": "survival",
    "生存": "survival",
    "欺瞒": "deception",
    "威吓": "intimidation",
    "表演": "performance",
    "说服": "persuasion",
}

DAMAGE_TERMS = {
    "钝击",
    "穿刺",
    "挥砍",
    "火焰",
    "寒冷",
    "闪电",
    "雷鸣",
    "强酸",
    "酸",
    "毒素",
    "毒性",
    "黯蚀",
    "坏死",
    "光耀",
    "力场",
    "心灵",
    "精神",
}

CONDITION_TERMS = {
    "目盲",
    "魅惑",
    "耳聋",
    "力竭",
    "恐慌",
    "受擒",
    "失能",
    "隐形",
    "麻痹",
    "石化",
    "中毒",
    "倒地",
    "束缚",
    "震慑",
    "昏迷",
}

SIZE_PATTERN = re.compile(r"^(中型或小型|大型或中型|小型或微型|超巨型|巨型|大型|中型|小型|微型)(.+)$")
CORE_HEADING_RE = re.compile(r"^#####\s+(.+?)\s*$", re.MULTILINE)
LEGACY_HEADING_RE = re.compile(r"^\*\*([^*\n]+[A-Za-z][^*\n]*)\*\*\s*$", re.MULTILINE)
OLD_SECTION_HEADER_RE = re.compile(
    r"^\*\*(?:动作Actions|附赠动作Bonus Actions|反应Reactions|传奇动作\s*Legendary Actions)\*\*\s*$",
    re.MULTILINE,
)


def clean_inline(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("***", "").replace("**", "").replace("*", "")
    value = value.replace("`", "")
    value = re.sub(r"[ \t\u3000]+", " ", value)
    value = re.sub(r"\s*\n\s*", " ", value)
    return value.strip()


def strip_title(value: str) -> str:
    return clean_inline(value).strip("。.:： ")


def split_bilingual_name(value: str) -> tuple[str, str]:
    name = strip_title(value)
    match = re.search(r"[A-Za-z]", name)
    if not match:
        return name, ""

    zh_name = name[: match.start()].strip(" -　")
    en_name = name[match.start() :].strip(" -　")
    return (zh_name or name), en_name


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug


def short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def source_from_path(path: Path) -> tuple[str, str]:
    parts = set(path.parts)
    if "怪物图鉴2025" in parts:
        return "MM25", "mm25"
    if "费资本的巨龙宝库" in parts:
        return "费资本的巨龙宝库", "ftod"
    return "DND5e 2024", "dnd5e-2024"


def make_monster_id(source_slug: str, zh_name: str, en_name: str, path: Path) -> str:
    slug = slugify(en_name) or slugify(path.stem)
    if not slug:
        slug = short_hash(f"{source_slug}:{zh_name}:{path}")
    return f"mon-{source_slug}-{slug}"


def ability_modifier(score: int) -> int:
    return (score - 10) // 2


def parse_signed_int(value: str) -> int | None:
    match = re.search(r"[+-]?\d+", value)
    if not match:
        return None
    return int(match.group(0))


def parse_creature_line(value: str) -> tuple[str, str, str]:
    line = clean_inline(value)
    left, sep, right = line.partition("，")
    if not sep:
        left, _, right = line.partition(",")

    size = "中型"
    creature_type = left.strip() or "未注明"
    match = SIZE_PATTERN.match(creature_type)
    if match:
        size = match.group(1)
        creature_type = match.group(2).strip() or "未注明"

    return size, creature_type, right.strip() or "未注明"


def first_metadata_line(block: str) -> str:
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("|") or stripped.startswith("#"):
            continue
        return stripped
    return ""


def extract_labeled_table_value(block: str, label: str) -> str:
    match = re.search(rf"\*\*{re.escape(label)}\*\*\s*([^|\n]+)", block)
    return clean_inline(match.group(1)) if match else ""


def extract_plain_line(block: str, label: str) -> str:
    match = re.search(rf"^{re.escape(label)}\s*([^\n]+)$", block, re.MULTILINE)
    return clean_inline(match.group(1)) if match else ""


def parse_list(value: str) -> list[str]:
    if not value or value in {"无", "-"}:
        return []
    parts = re.split(r"[；;、，,]", value)
    return [clean_inline(part) for part in parts if clean_inline(part)]


def split_immunities(value: str) -> tuple[list[str], list[str]]:
    damage: list[str] = []
    conditions: list[str] = []
    for item in parse_list(value):
        if item in CONDITION_TERMS:
            conditions.append(item)
        else:
            damage.append(item)
    return damage, conditions


def parse_bonus_map(value: str, name_map: dict[str, str] | None = None) -> dict[str, int]:
    bonuses: dict[str, int] = {}
    for part in parse_list(value):
        match = re.match(r"(.+?)\s*([+-]\d+)$", part)
        if not match:
            continue
        raw_name = clean_inline(match.group(1))
        name = name_map.get(raw_name, raw_name) if name_map else raw_name
        bonuses[name] = int(match.group(2))
    return bonuses


def parse_core_stats(block: str) -> tuple[Stats, dict[str, int]]:
    stats: dict[str, int] = {}
    saving_throws: dict[str, int] = {}
    for zh_name, field_name in ABILITY_COLUMNS:
        match = re.search(
            rf"\*\*{re.escape(zh_name)}\*\*\s*\|\s*(\d+)\s*\|\s*([+-]\d+)\s*\|\s*([+-]\d+)",
            block,
        )
        if not match:
            continue
        score = int(match.group(1))
        stats[field_name] = score
        saving_throws[field_name] = int(match.group(3))

    return Stats(**stats), saving_throws


def parse_legacy_stats(block: str) -> Stats:
    values: dict[str, int] = {}
    for zh_name, field_name in ABILITY_COLUMNS:
        match = re.search(rf"{re.escape(zh_name)}\s*(\d+)\s*[（(][^)）]+[)）]", block)
        if match:
            values[field_name] = int(match.group(1))
    return Stats(**values)


def parse_core_speed(block: str) -> tuple[int, str]:
    speed_text = extract_labeled_table_value(block, "速度")
    match = re.search(r"(\d+)\s*尺", speed_text)
    return (int(match.group(1)) if match else 30), speed_text


def parse_legacy_speed(block: str) -> tuple[int, str]:
    speed_text = extract_plain_line(block, "速度")
    match = re.search(r"(\d+)\s*尺", speed_text)
    return (int(match.group(1)) if match else 30), speed_text


def parse_entries(section: str) -> list[dict[str, str]]:
    entries: list[str] = []
    current = ""

    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("|") or line.startswith("#"):
            continue
        if re.match(r"^\*\*[^*].*?\*\*", line):
            if current:
                entries.append(current)
            current = line
        elif current:
            current = f"{current} {line}"

    if current:
        entries.append(current)

    parsed: list[dict[str, str]] = []
    for entry in entries:
        match = re.match(r"^\*\*(.+?)\*\*(.*)$", entry)
        if not match:
            continue
        title = strip_title(match.group(1))
        zh_name, _ = split_bilingual_name(title)
        description = clean_inline(match.group(2))
        if zh_name:
            parsed.append({"name": zh_name, "description": description})
    return parsed


def core_section(block: str, header: str) -> str:
    match = re.search(rf"^######\s*{re.escape(header)}.*$", block, re.MULTILINE)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"^######\s+", block[start:], re.MULTILINE)
    end = start + next_match.start() if next_match else len(block)
    return block[start:end]


def legacy_section(block: str, header_regex: str) -> str:
    match = re.search(rf"^\*\*{header_regex}\*\*\s*$", block, re.MULTILINE)
    if not match:
        return ""
    start = match.end()
    next_match = OLD_SECTION_HEADER_RE.search(block, start)
    end = next_match.start() if next_match else len(block)
    return block[start:end]


def legacy_traits(block: str) -> str:
    cr_match = re.search(r"^挑战等级\s*[^\n]+$", block, re.MULTILINE)
    action_match = re.search(r"^\*\*动作Actions\*\*\s*$", block, re.MULTILINE)
    if not cr_match or not action_match or action_match.start() <= cr_match.end():
        return ""
    return block[cr_match.end() : action_match.start()]


def parse_core_block(title: str, block: str, path: Path) -> dict[str, Any] | None:
    if "**AC**" not in block or "**HP**" not in block or "**CR**" not in block:
        return None

    zh_name, en_name = split_bilingual_name(title)
    source, source_slug = source_from_path(path)
    monster_id = make_monster_id(source_slug, zh_name, en_name, path)
    size, creature_type, alignment = parse_creature_line(first_metadata_line(block))

    ac_match = re.search(r"\*\*AC\*\*\s*(\d+)", block)
    hp_match = re.search(r"\*\*HP\*\*\s*(\d+)", block)
    init_match = re.search(r"\*\*先攻\*\*\s*([+-]\d+)", block)
    cr_match = re.search(r"\*\*CR\*\*\s*([0-9/]+)", block)
    pb_match = re.search(r"PB\s*\+\s*(\d+)", block)
    if not (ac_match and hp_match and cr_match):
        return None

    stats, saving_throws = parse_core_stats(block)
    speed, speed_text = parse_core_speed(block)
    damage_immunities, condition_immunities = split_immunities(extract_labeled_table_value(block, "免疫"))

    notes = [
        f"英文名：{en_name}" if en_name else "",
        f"速度：{speed_text}" if speed_text else "",
        f"来源文件：{path.relative_to(BACKEND_ROOT)}",
        "由本地 DND5e 2024 怪物图鉴条目抽取生成。",
    ]

    return {
        "monster_id": monster_id,
        "name": zh_name,
        "size": size,
        "creature_type": creature_type,
        "alignment": alignment,
        "challenge_rating": cr_match.group(1),
        "proficiency_bonus": int(pb_match.group(1)) if pb_match else proficiency_bonus_for_cr(cr_match.group(1)),
        "ac": int(ac_match.group(1)),
        "hp_max": int(hp_match.group(1)),
        "initiative_bonus": int(init_match.group(1)) if init_match else ability_modifier(stats.dexterity),
        "speed": speed,
        "stats": stats,
        "saving_throws": saving_throws,
        "skills": parse_bonus_map(extract_labeled_table_value(block, "技能"), SKILL_NAME_MAP),
        "senses": parse_list(extract_labeled_table_value(block, "感官")),
        "languages": parse_list(extract_labeled_table_value(block, "语言")),
        "damage_resistances": parse_list(extract_labeled_table_value(block, "抗性")),
        "damage_immunities": damage_immunities,
        "damage_vulnerabilities": parse_list(extract_labeled_table_value(block, "易伤")),
        "condition_immunities": condition_immunities,
        "traits": parse_entries(core_section(block, "特质Traits")),
        "actions": parse_entries(core_section(block, "动作Actions")),
        "bonus_actions": parse_entries(core_section(block, "附赠动作Bonus Actions")),
        "reactions": parse_entries(core_section(block, "反应Reactions")),
        "notes": "\n".join(item for item in notes if item),
        "source": source,
    }


def parse_legacy_block(title: str, block: str, path: Path) -> dict[str, Any] | None:
    if "护甲等级" not in block or "生命值" not in block or "挑战等级" not in block:
        return None

    zh_name, en_name = split_bilingual_name(title)
    source, source_slug = source_from_path(path)
    monster_id = make_monster_id(source_slug, zh_name, en_name, path)
    size, creature_type, alignment = parse_creature_line(first_metadata_line(block))

    ac_match = re.search(r"^护甲等级\s*(\d+)", block, re.MULTILINE)
    hp_match = re.search(r"^生命值\s*(\d+)", block, re.MULTILINE)
    cr_match = re.search(r"^挑战等级\s*([0-9/]+)", block, re.MULTILINE)
    pb_match = re.search(r"熟练加值\s*\+\s*(\d+)", block)
    if not (ac_match and hp_match and cr_match):
        return None

    stats = parse_legacy_stats(block)
    speed, speed_text = parse_legacy_speed(block)
    damage_immunities, condition_immunities = split_immunities(extract_plain_line(block, "伤害免疫"))
    explicit_conditions = parse_list(extract_plain_line(block, "状态免疫"))
    condition_immunities.extend(item for item in explicit_conditions if item not in condition_immunities)

    notes = [
        f"英文名：{en_name}" if en_name else "",
        f"速度：{speed_text}" if speed_text else "",
        f"来源文件：{path.relative_to(BACKEND_ROOT)}",
        "由本地 DND5e 2024 怪物图鉴条目抽取生成。",
    ]

    return {
        "monster_id": monster_id,
        "name": zh_name,
        "size": size,
        "creature_type": creature_type,
        "alignment": alignment,
        "challenge_rating": cr_match.group(1),
        "proficiency_bonus": int(pb_match.group(1)) if pb_match else proficiency_bonus_for_cr(cr_match.group(1)),
        "ac": int(ac_match.group(1)),
        "hp_max": int(hp_match.group(1)),
        "initiative_bonus": ability_modifier(stats.dexterity),
        "speed": speed,
        "stats": stats,
        "saving_throws": parse_bonus_map(extract_plain_line(block, "豁免"), {zh: en for zh, en in ABILITY_COLUMNS}),
        "skills": parse_bonus_map(extract_plain_line(block, "技能"), SKILL_NAME_MAP),
        "senses": parse_list(extract_plain_line(block, "感官")),
        "languages": parse_list(extract_plain_line(block, "语言")),
        "damage_resistances": parse_list(extract_plain_line(block, "伤害抗性")),
        "damage_immunities": damage_immunities,
        "damage_vulnerabilities": parse_list(extract_plain_line(block, "伤害易伤")),
        "condition_immunities": condition_immunities,
        "traits": parse_entries(legacy_traits(block)),
        "actions": parse_entries(legacy_section(block, r"动作Actions")),
        "bonus_actions": parse_entries(legacy_section(block, r"附赠动作Bonus Actions")),
        "reactions": parse_entries(legacy_section(block, r"反应Reactions")),
        "notes": "\n".join(item for item in notes if item),
        "source": source,
    }


def parse_core_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    matches = list(CORE_HEADING_RE.finditer(text))
    templates: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        parsed = parse_core_block(match.group(1), text[start:end], path)
        if parsed:
            templates.append(parsed)
    return templates


def legacy_monster_starts(text: str) -> list[re.Match[str]]:
    starts: list[re.Match[str]] = []
    for match in LEGACY_HEADING_RE.finditer(text):
        lookahead = text[match.end() : match.end() + 900]
        if "护甲等级" in lookahead and "生命值" in lookahead and "挑战等级" in lookahead:
            starts.append(match)
    return starts


def parse_legacy_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    matches = legacy_monster_starts(text)
    templates: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        parsed = parse_legacy_block(match.group(1), text[start:end], path)
        if parsed:
            templates.append(parsed)
    return templates


def cr_to_float(value: str) -> float:
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return 1.0


def proficiency_bonus_for_cr(value: str) -> int:
    cr = cr_to_float(value)
    if cr <= 4:
        return 2
    if cr <= 8:
        return 3
    if cr <= 12:
        return 4
    if cr <= 16:
        return 5
    if cr <= 20:
        return 6
    if cr <= 24:
        return 7
    if cr <= 28:
        return 8
    return 9


def estimate_hp(value: str, size: str) -> int:
    cr = cr_to_float(value)
    if cr <= 0:
        base = 4
    elif cr <= 0.125:
        base = 7
    elif cr <= 0.25:
        base = 11
    elif cr <= 0.5:
        base = 18
    elif cr <= 1:
        base = 30
    else:
        base = 30 + int(cr * 16)

    size_factor = {
        "微型": 0.5,
        "小型": 0.75,
        "中型": 1.0,
        "中型或小型": 0.9,
        "大型": 1.25,
        "巨型": 1.5,
        "超巨型": 2.0,
    }.get(size, 1.0)
    return max(1, round(base * size_factor))


def estimate_stats(value: str, size: str, creature_type: str) -> Stats:
    cr = cr_to_float(value)
    size_strength = {"微型": -6, "小型": -2, "中型": 0, "中型或小型": -1, "大型": 4, "巨型": 7, "超巨型": 10}.get(size, 0)
    power = min(10, int(cr // 2))
    dex = 14 if any(token in creature_type for token in ("妖精", "类人", "元素", "野兽")) else 12
    intelligence = 10
    wisdom = 10
    charisma = 10
    if any(token in creature_type for token in ("龙类", "邪魔", "天界", "妖精", "异怪")):
        intelligence += min(6, int(cr // 4) + 2)
        wisdom += min(4, int(cr // 5) + 1)
        charisma += min(6, int(cr // 4) + 2)
    return Stats(
        strength=max(1, min(30, 10 + size_strength + power)),
        dexterity=max(1, min(30, dex + min(4, int(cr // 6)))),
        constitution=max(1, min(30, 10 + max(0, size_strength // 2) + power)),
        intelligence=max(1, min(30, intelligence)),
        wisdom=max(1, min(30, wisdom)),
        charisma=max(1, min(30, charisma)),
    )


def estimated_index_template(name_cell: str, size: str, creature_type: str, cr: str, source: str, path: Path) -> dict[str, Any]:
    zh_name, en_name = split_bilingual_name(name_cell)
    source_slug = slugify(source) or "index"
    monster_id = make_monster_id(source_slug, zh_name, en_name, path)
    stats = estimate_stats(cr, size, creature_type)
    pb = proficiency_bonus_for_cr(cr)
    ability_bonus = max(ability_modifier(stats.strength), ability_modifier(stats.dexterity))
    attack_bonus = pb + ability_bonus
    damage_expr = "1d6+2" if cr_to_float(cr) < 2 else f"{max(1, int(cr_to_float(cr) // 2) + 1)}d6+{max(1, ability_bonus)}"
    return {
        "monster_id": monster_id,
        "name": zh_name,
        "size": size or "中型",
        "creature_type": creature_type or "未注明",
        "alignment": "未注明",
        "challenge_rating": cr or "1",
        "proficiency_bonus": pb,
        "ac": max(10, min(22, 12 + int(cr_to_float(cr) // 4))),
        "hp_max": estimate_hp(cr, size),
        "initiative_bonus": ability_modifier(stats.dexterity),
        "speed": 30,
        "stats": stats,
        "saving_throws": {},
        "skills": {},
        "senses": ["被动察觉10"],
        "languages": [],
        "damage_resistances": [],
        "damage_immunities": [],
        "damage_vulnerabilities": [],
        "condition_immunities": [],
        "traits": [
            {
                "name": "索引基础模板",
                "description": "此模板由速查索引生成，仅包含名称、体型、类型、挑战等级与估算战斗数值；详细能力以原始怪物条目为准。",
            }
        ],
        "actions": [
            {
                "name": "基础攻击",
                "description": f"近战或远程攻击：+{attack_bonus}，触及5尺或射程30尺。命中：{damage_expr}钝击伤害。",
            }
        ],
        "bonus_actions": [],
        "reactions": [],
        "notes": f"英文名：{en_name}\n来源文件：{path.relative_to(BACKEND_ROOT)}\n由本地速查索引估算生成。",
        "source": source or "速查索引",
    }


def english_name_from_notes(value: str) -> str:
    match = re.search(r"^英文名：(.+)$", value, re.MULTILINE)
    return clean_inline(match.group(1)) if match else ""


def parse_index_fallbacks(
    docs_root: Path,
    existing_name_keys: set[tuple[str, str]],
    existing_english_keys: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    index_path = docs_root / "速查" / "5E万兽大全.md"
    if not index_path.exists():
        return []

    templates: list[dict[str, Any]] = []
    for line in index_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped.startswith("| ["):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 6:
            continue
        link_match = re.match(r"\[(.+?)\]\((.+?)\)", cells[0])
        if not link_match:
            continue
        zh_name, en_name = split_bilingual_name(link_match.group(1))
        source = clean_inline(cells[5])
        name_key = (zh_name, source)
        english_key = (slugify(en_name), source)
        if name_key in existing_name_keys or english_key in existing_english_keys:
            continue
        templates.append(estimated_index_template(link_match.group(1), clean_inline(cells[1]), clean_inline(cells[2]), clean_inline(cells[4]), source, index_path))
    return templates


def iter_monster_markdown_files(docs_root: Path) -> list[Path]:
    if not docs_root.exists():
        raise FileNotFoundError(f"Documents root does not exist: {docs_root}")
    return sorted(path for path in docs_root.rglob("*.md") if any("怪物图鉴" in part for part in path.parts) and path.name != "注释.md")


def uniquify_templates(raw_templates: list[dict[str, Any]]) -> list[MonsterTemplate]:
    seen_ids: set[str] = set()
    templates: list[MonsterTemplate] = []
    for data in raw_templates:
        monster_id = str(data["monster_id"])
        if monster_id in seen_ids:
            monster_id = f"{monster_id}-{short_hash(data['name'] + data.get('notes', ''))}"
            data = {**data, "monster_id": monster_id}
        seen_ids.add(monster_id)
        templates.append(MonsterTemplate.model_validate(data))
    return templates


def clean_generated_files(output_dir: Path) -> int:
    prefixes = ("mon-mm25-", "mon-ftod-", "mon-dnd5e-2024-")
    removed = 0
    for path in output_dir.glob("*.json"):
        if path.name.startswith(prefixes):
            path.unlink()
            removed += 1
    return removed


def write_templates(templates: list[MonsterTemplate], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for template in templates:
        path = output_dir / f"{safe_file_stem(template.monster_id)}.json"
        path.write_text(template.model_dump_json(indent=2), encoding="utf-8")


def generate(docs_root: Path, output_dir: Path, clean_generated: bool) -> dict[str, int]:
    raw_templates: list[dict[str, Any]] = []
    core_count = 0
    legacy_count = 0

    for path in iter_monster_markdown_files(docs_root):
        core_templates = parse_core_file(path)
        legacy_templates = parse_legacy_file(path)
        core_count += len(core_templates)
        legacy_count += len(legacy_templates)
        raw_templates.extend(core_templates)
        raw_templates.extend(legacy_templates)

    existing_name_keys = {(item["name"], item["source"]) for item in raw_templates}
    existing_english_keys = {
        (english_slug, item["source"])
        for item in raw_templates
        for english_slug in [slugify(english_name_from_notes(item.get("notes", "")))]
        if english_slug
    }
    fallback_templates = parse_index_fallbacks(docs_root, existing_name_keys, existing_english_keys)
    raw_templates.extend(fallback_templates)

    templates = uniquify_templates(raw_templates)
    removed = clean_generated_files(output_dir) if clean_generated else 0
    write_templates(templates, output_dir)

    return {
        "core_statblocks": core_count,
        "legacy_statblocks": legacy_count,
        "index_fallbacks": len(fallback_templates),
        "written": len(templates),
        "removed_old_generated": removed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate local monster templates from DND5e 2024 markdown.")
    parser.add_argument("--docs-root", type=Path, default=BACKEND_ROOT / "Documents" / "DND5e 2024")
    parser.add_argument("--output-dir", type=Path, default=BACKEND_ROOT / "Monsters")
    parser.add_argument("--clean-generated", action="store_true", help="Remove previously generated MM25/FToD JSON before writing.")
    args = parser.parse_args()

    summary = generate(args.docs_root, args.output_dir, args.clean_generated)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

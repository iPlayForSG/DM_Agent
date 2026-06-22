"""Generate starter adventure hooks and parse model-created adventure hooks."""

import json
import re
from typing import Iterable, List

from models import AdventureHook, Character, stable_id


AI_GENERATED_ADVENTURE_ID = "adv-ai-generated"


# Fixed seeds keep early-game QA stable while still rotating by party makeup.
ADVENTURE_TEMPLATES = [
    {
        "adventure_id": "adv-ashes-under-blackbarrow",
        "title": "黑冢下的余烬",
        "summary": "一座矿业村落在旧墓丘下方的封闭墓道冒出烟雾后陷入死寂。",
        "tone": "阴郁",
        "difficulty": "中等",
        "opening_scene": "队伍抵达一座雨水浸透的边境村庄，那里每根烟囱都冷透了，唯有一处仍冒着烟。",
    },
    {
        "adventure_id": "adv-the-lantern-road-debt",
        "title": "灯路旧债",
        "summary": "一家商会出钱雇人护送货队，但那条道路两侧满是失踪商队与讨债亡魂的传闻。",
        "tone": "黑暗奇幻",
        "difficulty": "简单",
        "opening_scene": "疲惫的商会代理人把一本染血账册摊在酒馆桌上，说出了那条没人愿意踏上的道路名字。",
    },
    {
        "adventure_id": "adv-the-broken-chapel-bell",
        "title": "破礼拜堂之钟",
        "summary": "山坡废弃神殿会在无月之夜自行鸣响，每一声钟响后都会有一名村民失踪。",
        "tone": "恐怖",
        "difficulty": "中等",
        "opening_scene": "钟声越过山谷响了一下，而祭司坚持说那座礼拜堂既没有钟绳，也没有活着的看守。",
    },
    {
        "adventure_id": "adv-knives-at-lowwater-market",
        "title": "低水集市的刀影",
        "summary": "一座河畔集镇正被勒索、破坏，以及雇佣刀手与绝望行会成员之间的仇怨拖入腐败。",
        "tone": "街头冒险",
        "difficulty": "中等",
        "opening_scene": "鱼市尚未收摊，第一具尸体便砸落在计数桌上。",
    },
]


NON_DND_FOLKLORE_TERMS = [
    "土地龛",
    "土地庙",
    "土地公",
    "城隍",
    "庙祝",
    "祠堂",
    "废祠",
    "香灰",
    "纸钱",
    "符箓",
    "道士",
    "法坛",
    "义庄",
    "冥婚",
    "黄皮子",
    "狐仙",
    "灶王",
    "地府",
    "阴差",
    "阎王",
    "山神",
    "饿鬼",
    "饿鬼婆",
    "黑陶瓮",
    "陶瓮",
]


DND_ADVENTURE_ANCHORS = [
    "d&d",
    "费伦",
    "剑湾",
    "被遗忘国度",
    "灰鹰",
    "博德之门",
    "深水城",
    "无冬城",
    "烛堡",
    "银月城",
    "科米尔",
    "安姆",
    "至高森林",
    "散塔林",
    "竖琴手",
    "领主联盟",
    "红袍法师",
    "地城",
    "神殿",
    "酒馆",
    "商队",
    "行会",
    "公会",
    "商会",
    "矿坑",
    "废墟",
    "邪教",
    "冒险者",
    "不死生物",
    "亡灵",
    "骷髅",
    "地精",
    "狗头人",
    "豺狼人",
    "兽人",
    "食人魔",
    "巨魔",
    "巫妖",
    "眼魔",
    "夺心魔",
    "巨龙",
    "恶魔",
    "魔鬼",
    "牧师",
    "圣武士",
    "法师",
    "游侠",
    "游荡者",
    "吟游诗人",
    "术士",
    "德鲁伊",
    "战士",
]


def generate_initial_adventures(characters: List[Character]) -> List[AdventureHook]:
    # Rotate the template list so different parties do not always see the same first option.
    party_seed = sum(len(character.name) + character.level for character in characters) if characters else 0
    rotated = ADVENTURE_TEMPLATES[party_seed % len(ADVENTURE_TEMPLATES) :] + ADVENTURE_TEMPLATES[: party_seed % len(ADVENTURE_TEMPLATES)]

    hooks: List[AdventureHook] = []
    for template in rotated[:3]:
        hooks.append(AdventureHook(**template))
    hooks.append(ai_generated_adventure_option())
    return hooks


def ai_generated_adventure_option() -> AdventureHook:
    return AdventureHook(
        adventure_id=AI_GENERATED_ADVENTURE_ID,
        title="让 DM 即兴生成",
        summary="根据当前队伍构成，由主持人现场构思一段全新的冒险背景与开场。",
        tone="由主持人决定",
        difficulty="适合当前队伍",
        opening_scene="",
    )


def is_ai_generated_adventure_id(adventure_id: str) -> bool:
    return str(adventure_id or "").strip() == AI_GENERATED_ADVENTURE_ID


def is_model_generated_adventure_id(adventure_id: str) -> bool:
    normalized = str(adventure_id or "").strip()
    return normalized.startswith("adv-ai-") and normalized != AI_GENERATED_ADVENTURE_ID


def ensure_ai_generated_adventure_option(hooks: Iterable[AdventureHook]) -> List[AdventureHook]:
    normalized = list(hooks or [])
    if any(is_ai_generated_adventure_id(hook.adventure_id) for hook in normalized):
        return normalized
    return [*normalized, ai_generated_adventure_option()]


def build_ai_adventure_prompt(characters: Iterable[Character], existing_hooks: Iterable[AdventureHook]) -> str:
    party_lines = []
    for character in characters or []:
        party_lines.append(
            "- "
            f"{character.name}，{character.level}级，"
            f"{character.species or character.race}，"
            f"{character.class_name}，背景：{character.background_name or character.background or '未指定'}。"
        )
    if not party_lines:
        party_lines.append("- 当前队伍信息不完整，请生成适合1级冒险者的开局。")

    existing_titles = [
        hook.title
        for hook in existing_hooks or []
        if hook.title and not is_ai_generated_adventure_id(hook.adventure_id)
    ]
    existing_line = "、".join(existing_titles) if existing_titles else "无"

    return f"""你是中文 D&D 2024 地城主持人。请为当前队伍生成一个新的短冒险开局，必须不同于已有选项。

队伍：
{chr(10).join(party_lines)}

已有冒险标题：{existing_line}

D&D 风格限制：
- 必须是 D&D 西式奇幻跑团语境，优先贴近被遗忘国度、剑湾、灰鹰或同类 D&D 兼容世界。
- 场景应使用 D&D 常见地点与组织：边境村镇、酒馆、神殿、地城、废墟、矿坑、商队、行会、冒险者公会、地方守卫、竖琴手、散塔林会、领主联盟等。
- 威胁应来自 D&D 常见怪物、阵营或魔法冲突：地精、狗头人、豺狼人、兽人、不死生物、邪教徒、魔鬼、恶魔、巨龙爪牙、红袍法师、诅咒魔法等。
- 不要写中式志怪、乡土民俗、武侠、仙侠、东方鬼神或民间传说。禁止土地龛、土地庙、祠堂、庙祝、香灰、纸钱、道士、符箓、城隍、饿鬼、地府、阴差、阎王、山神、黑陶瓮等元素。
- 可以使用中文叙述，但名词与世界观必须像 D&D 冒险，而不是中国民俗故事。

输出要求：
- 只输出一个 JSON 对象，不要 Markdown，不要代码块，不要额外解释。
- 所有字段使用中文。
- 冒险适合当前队伍等级，保持严肃、可跑团、可继续推进，不要写成宣传文案。
- 开场要有具体地点、可行动的眼前矛盾、至少一个可调查线索或 NPC 压力点。
- summary 或 opening_scene 至少包含一个清晰的 D&D 锚点，例如“神殿”“地城”“酒馆”“行会”“商队”“地精”“狗头人”“邪教徒”“不死生物”“散塔林会”“竖琴手”等。
- 不要提及“工具”“系统”“模型”“生成”或开发者视角。

JSON 字段：
{{
  "title": "2到10个汉字的冒险标题",
  "summary": "一句话概括冒险背景和核心冲突",
  "tone": "冒险基调，例如阴郁、诡秘、街头冒险、荒野惊悚",
  "difficulty": "简单、中等或困难",
  "opening_scene": "第二人称开场场景，120到220字，结尾给玩家一个明确但开放的第一步选择"
}}"""


def parse_generated_adventure(raw_text: str) -> AdventureHook:
    payload = _extract_json_object(raw_text)
    required_fields = ("title", "summary", "tone", "difficulty", "opening_scene")
    missing = [field for field in required_fields if not str(payload.get(field) or "").strip()]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")

    cleaned = {field: str(payload[field]).strip() for field in required_fields}
    cleaned["adventure_id"] = stable_id("adv-ai", cleaned["title"])
    if is_ai_generated_adventure_id(cleaned["adventure_id"]):
        raise ValueError("generated adventure id conflicts with the AI option id")
    hook = AdventureHook(**cleaned)
    validate_dnd_adventure_theme(hook)
    return hook


def validate_dnd_adventure_theme(hook: AdventureHook) -> None:
    combined = "\n".join(
        [
            hook.title or "",
            hook.summary or "",
            hook.tone or "",
            hook.opening_scene or "",
        ]
    ).lower()
    banned_terms = [term for term in NON_DND_FOLKLORE_TERMS if term.lower() in combined]
    if banned_terms:
        raise ValueError(f"non-D&D folklore terms detected: {', '.join(banned_terms[:6])}")

    if not any(anchor.lower() in combined for anchor in DND_ADVENTURE_ANCHORS):
        raise ValueError("missing D&D adventure anchor such as a D&D location, faction, monster, class, or dungeon element")


def _extract_json_object(raw_text: str) -> dict:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("empty model response")

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.IGNORECASE | re.DOTALL)
    if fenced_match:
        text = fenced_match.group(1).strip()
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model response did not contain a JSON object")
        text = text[start : end + 1]

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("generated adventure payload must be a JSON object")
    return payload

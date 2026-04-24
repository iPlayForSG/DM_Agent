"""Generate deterministic starter adventure hooks from a fixed template pool."""

from typing import List

from models import AdventureHook, Character


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
        "summary": "山坡废祠会在无月之夜自行鸣响，每一声钟响后都会有一名村民失踪。",
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


def generate_initial_adventures(characters: List[Character]) -> List[AdventureHook]:
    # Rotate the template list so different parties do not always see the same first option.
    party_seed = sum(len(character.name) + character.level for character in characters) if characters else 0
    rotated = ADVENTURE_TEMPLATES[party_seed % len(ADVENTURE_TEMPLATES) :] + ADVENTURE_TEMPLATES[: party_seed % len(ADVENTURE_TEMPLATES)]

    hooks: List[AdventureHook] = []
    for template in rotated[:3]:
        hooks.append(AdventureHook(**template))
    return hooks

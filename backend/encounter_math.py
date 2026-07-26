"""Deterministic encounter budgeting and challenge-rating math.

Tables and algorithms are ported from the 5e.tools open-source toolset
(https://5e.tools, https://github.com/5etools-mirror-3/5etools-src):

- ``XP_BY_CR``            -> ``Parser.XP_CHART_ALT`` in ``js/parser.js``
- ``TIER_TO_LEVEL_XP``    -> ``js/encounterbuilder/consts/encounterbuilder-consts-one.js``
                             (2024 XP budget, XDMG p.114 "Combat Encounter Difficulty")
- ``MONSTER_STATS_BY_CR`` -> ``data/msbcr.json``
- ``estimate_challenge_rating`` -> ``calculateCr()`` in ``js/crcalculator.js``

Only the numeric tables and the derivation logic are reproduced here; none of the
5e.tools UI, rendering, or prose content is vendored. Everything below is pure
computation over caller-supplied numbers so it stays framework-neutral and
testable without a model or a running game.
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Challenge rating -> experience points.
XP_BY_CR: Dict[str, int] = {
    "0": 10,
    "1/8": 25,
    "1/4": 50,
    "1/2": 100,
    "1": 200,
    "2": 450,
    "3": 700,
    "4": 1100,
    "5": 1800,
    "6": 2300,
    "7": 2900,
    "8": 3900,
    "9": 5000,
    "10": 5900,
    "11": 7200,
    "12": 8400,
    "13": 10000,
    "14": 11500,
    "15": 13000,
    "16": 15000,
    "17": 18000,
    "18": 20000,
    "19": 22000,
    "20": 25000,
    "21": 33000,
    "22": 41000,
    "23": 50000,
    "24": 62000,
    "25": 75000,
    "26": 90000,
    "27": 105000,
    "28": 120000,
    "29": 135000,
    "30": 155000,
}

# Per-character XP budget indexed by character level (index 0 is unused).
TIER_TO_LEVEL_XP: Dict[str, List[int]] = {
    "low": [0, 50, 100, 150, 250, 500, 600, 750, 1000, 1300, 1600, 1900, 2200, 2600, 2900, 3300, 3800, 4500, 5000, 5500, 6400],
    "moderate": [0, 75, 150, 225, 375, 750, 1000, 1300, 1700, 2000, 2300, 2900, 3700, 4200, 4900, 5400, 6100, 7200, 8700, 10700, 13200],
    "high": [0, 100, 200, 400, 500, 1100, 1400, 1700, 2100, 2600, 3100, 4100, 4700, 5400, 6200, 7800, 9800, 11700, 14200, 17200, 22000],
}

TIERS: Tuple[str, ...] = ("low", "moderate", "high")
TIER_ABSURD = "absurd"
MAX_CHARACTER_LEVEL = len(TIER_TO_LEVEL_XP["low"]) - 1

DIFFICULTY_LABELS: Dict[str, str] = {
    "trivial": "微不足道",
    "low": "低难度",
    "moderate": "中等难度",
    "high": "高难度",
    TIER_ABSURD: "超出预算",
}

# (cr, proficiency_bonus, ac, hp_min, hp_max, attack_bonus, dpr_min, dpr_max, save_dc)
MONSTER_STATS_BY_CR: Tuple[Tuple[str, int, int, int, int, int, int, int, int], ...] = (
    ("0", 2, 13, 1, 6, 3, 0, 1, 13),
    ("1/8", 2, 13, 7, 35, 3, 2, 3, 13),
    ("1/4", 2, 13, 36, 49, 3, 4, 5, 13),
    ("1/2", 2, 13, 50, 70, 3, 6, 8, 13),
    ("1", 2, 13, 71, 85, 3, 9, 14, 13),
    ("2", 2, 13, 86, 100, 3, 15, 20, 13),
    ("3", 2, 13, 101, 115, 4, 21, 26, 13),
    ("4", 2, 14, 116, 130, 5, 27, 32, 14),
    ("5", 3, 15, 131, 145, 6, 33, 38, 15),
    ("6", 3, 15, 146, 160, 6, 39, 44, 15),
    ("7", 3, 15, 161, 175, 6, 45, 50, 15),
    ("8", 3, 16, 176, 190, 7, 51, 56, 16),
    ("9", 4, 16, 191, 205, 7, 57, 62, 16),
    ("10", 4, 17, 206, 220, 7, 63, 68, 16),
    ("11", 4, 17, 221, 235, 8, 69, 74, 17),
    ("12", 4, 17, 236, 250, 8, 75, 80, 18),
    ("13", 5, 18, 251, 265, 8, 81, 86, 18),
    ("14", 5, 18, 266, 280, 8, 87, 92, 18),
    ("15", 5, 18, 281, 295, 8, 93, 98, 18),
    ("16", 5, 18, 296, 310, 9, 99, 104, 18),
    ("17", 6, 19, 311, 325, 10, 105, 110, 19),
    ("18", 6, 19, 326, 340, 10, 111, 116, 19),
    ("19", 6, 19, 341, 355, 10, 117, 122, 19),
    ("20", 6, 19, 356, 400, 10, 123, 140, 19),
    ("21", 7, 19, 401, 445, 11, 141, 158, 20),
    ("22", 7, 19, 446, 490, 11, 159, 176, 20),
    ("23", 7, 19, 491, 535, 11, 177, 194, 20),
    ("24", 7, 19, 536, 580, 11, 195, 212, 21),
    ("25", 8, 19, 581, 625, 12, 213, 230, 21),
    ("26", 8, 19, 626, 670, 12, 231, 248, 21),
    ("27", 8, 19, 671, 715, 13, 249, 266, 22),
    ("28", 8, 19, 716, 760, 13, 267, 284, 22),
    ("29", 9, 19, 760, 805, 13, 285, 302, 22),
    ("30", 9, 19, 805, 850, 14, 303, 320, 23),
)

CR_ORDER: Tuple[str, ...] = tuple(row[0] for row in MONSTER_STATS_BY_CR)

# The CR calculator clamps inputs so an extreme stat block cannot index past CR 30.
MAX_RATED_HP = 850
MAX_RATED_DPR = 320


def normalize_cr(value: Any) -> str:
    """Return a canonical CR key, accepting 0.5/'0.5'/'1/2'/'½' style inputs."""

    if value is None:
        return ""
    text = str(value).strip().replace("½", "1/2").replace("¼", "1/4").replace("⅛", "1/8")
    if not text:
        return ""
    if text in XP_BY_CR:
        return text
    try:
        number = float(text)
    except ValueError:
        return ""
    for key, decimal in (("1/8", 0.125), ("1/4", 0.25), ("1/2", 0.5)):
        if abs(number - decimal) < 1e-9:
            return key
    if number.is_integer() and str(int(number)) in XP_BY_CR:
        return str(int(number))
    return ""


def cr_to_decimal(cr: str) -> float:
    if not cr or cr == "0":
        return 0.0
    if "/" in cr:
        numerator, _, denominator = cr.partition("/")
        return float(numerator) / float(denominator)
    return float(cr)


def xp_for_cr(cr: Any) -> Optional[int]:
    normalized = normalize_cr(cr)
    if not normalized:
        return None
    return XP_BY_CR[normalized]


def party_xp_budget(levels: Sequence[int]) -> Dict[str, int]:
    """Sum the per-character XP budget for each difficulty tier.

    ``absurd`` extrapolates the 5e.tools thermometer: ``high + (high - moderate)``.
    """

    budget: Dict[str, int] = {}
    for tier in TIERS:
        table = TIER_TO_LEVEL_XP[tier]
        budget[tier] = sum(table[min(max(int(level), 1), MAX_CHARACTER_LEVEL)] for level in levels)
    budget[TIER_ABSURD] = budget["high"] + (budget["high"] - budget["moderate"])
    return budget


def classify_encounter(total_xp: int, budget: Dict[str, int]) -> str:
    """Return the highest tier the encounter's XP actually reaches."""

    if total_xp >= budget[TIER_ABSURD]:
        return TIER_ABSURD
    for tier in reversed(TIERS):
        if total_xp >= budget[tier]:
            return tier
    return "trivial"


def estimate_encounter_difficulty(
    party_levels: Sequence[int],
    enemies: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Score one encounter against the 2024 party XP budget."""

    levels = [int(level) for level in party_levels if int(level) > 0]
    if not levels:
        raise ValueError("At least one party member level is required.")

    budget = party_xp_budget(levels)
    breakdown: List[Dict[str, Any]] = []
    unknown: List[str] = []
    total_xp = 0

    for entry in enemies:
        raw_cr = entry.get("challenge_rating", entry.get("cr"))
        name = str(entry.get("name") or "").strip() or "未命名敌人"
        try:
            count = int(entry.get("count", 1))
        except (TypeError, ValueError):
            count = 1
        count = max(1, count)

        normalized = normalize_cr(raw_cr)
        if not normalized:
            unknown.append(f"{name}({raw_cr})")
            continue

        each_xp = XP_BY_CR[normalized]
        group_xp = each_xp * count
        total_xp += group_xp
        row = {
            "name": name,
            "challenge_rating": normalized,
            "count": count,
            "xp_each": each_xp,
            "xp_total": group_xp,
        }
        # 调用方可以标注该 CR 是权威模板还是估算值；估算结果必须一路透传给读者。
        if entry.get("cr_source"):
            row["cr_source"] = str(entry["cr_source"])
        breakdown.append(row)

    tier = classify_encounter(total_xp, budget)
    return {
        "party_levels": levels,
        "party_size": len(levels),
        "budget": budget,
        "encounter_xp": total_xp,
        "difficulty": tier,
        "difficulty_label": DIFFICULTY_LABELS.get(tier, tier),
        "breakdown": breakdown,
        "unknown_challenge_ratings": unknown,
        "xp_to_next_tier": _xp_to_next_tier(total_xp, budget),
    }


def _xp_to_next_tier(total_xp: int, budget: Dict[str, int]) -> Dict[str, int]:
    remaining: Dict[str, int] = {}
    for tier in (*TIERS, TIER_ABSURD):
        delta = budget[tier] - total_xp
        if delta > 0:
            remaining[tier] = delta
    return remaining


def _clamped_index(index: int) -> int:
    return max(0, min(index, len(MONSTER_STATS_BY_CR) - 1))


def _rating_from_defense(hp: int, ac: int) -> Optional[str]:
    for index, row in enumerate(MONSTER_STATS_BY_CR):
        _, _, row_ac, hp_min, hp_max, _, _, _, _ = row
        if hp_min <= hp <= hp_max:
            # 每偏离 2 点 AC 调整一个 CR 档，向零取整，与 5e.tools 的实现一致。
            difference = row_ac - ac
            difference = difference // 2 if difference > 0 else -((-difference) // 2)
            return MONSTER_STATS_BY_CR[_clamped_index(index - difference)][0]
    return None


def defensive_challenge_rating(hp: int, ac: int) -> Optional[str]:
    """Public defence-only CR, for combatants improvised without a stat block.

    Encounters started with raw HP/AC have no declared CR and no known damage
    output, so only the defensive half of the calculator can be applied. Callers
    must label results derived this way as approximate.
    """

    if hp <= 0 or ac <= 0:
        return None
    return _rating_from_defense(min(int(hp), MAX_RATED_HP), int(ac))


def _rating_from_offense(dpr: int, attack_value: int, use_save_dc: bool) -> Optional[str]:
    for index, row in enumerate(MONSTER_STATS_BY_CR):
        _, _, _, _, _, row_attack, dpr_min, dpr_max, row_save_dc = row
        if dpr_min <= dpr <= dpr_max:
            baseline = row_save_dc if use_save_dc else row_attack
            difference = baseline - attack_value
            difference = difference // 2 if difference > 0 else -((-difference) // 2)
            return MONSTER_STATS_BY_CR[_clamped_index(index - difference)][0]
    return None


# 两个 CR 平均后只可能落在有限几个分数上，5e.tools 用精确值表把它们折回官方 CR 档。
# 这里逐项镜像该表；其余带小数的结果四舍五入（JS 的 Math.round 是 floor(x+0.5)，
# 与 Python 的银行家舍入不同，必须显式实现）。
_FRACTIONAL_CR_BUCKETS: Dict[float, str] = {
    0.5625: "1/2",
    0.5: "1/2",
    0.375: "1/4",
    0.3125: "1/4",
    0.25: "1/4",
    0.1875: "1/8",
    0.125: "1/8",
    0.0625: "1/8",
}


def _decimal_to_cr(value: float) -> str:
    for bucket, cr in _FRACTIONAL_CR_BUCKETS.items():
        if abs(value - bucket) < 1e-9:
            return cr
    if float(value).is_integer():
        return str(int(value))
    return str(int(math.floor(value + 0.5)))


def estimate_challenge_rating(
    hp: int,
    ac: int,
    damage_per_round: int,
    attack_bonus: int = 0,
    save_dc: int = 0,
) -> Dict[str, Any]:
    """Average defensive and offensive CR the way the 5e.tools calculator does.

    ``save_dc`` replaces ``attack_bonus`` when the creature's main threat is a
    save-based effect, mirroring the calculator's "save instead" toggle.
    """

    if hp <= 0:
        raise ValueError("hp must be a positive number.")
    if ac <= 0:
        raise ValueError("ac must be a positive number.")
    if damage_per_round < 0:
        raise ValueError("damage_per_round cannot be negative.")

    use_save_dc = bool(save_dc)
    attack_value = int(save_dc) if use_save_dc else int(attack_bonus)

    rated_hp = min(int(hp), MAX_RATED_HP)
    rated_dpr = min(int(damage_per_round), MAX_RATED_DPR)

    defensive_cr = _rating_from_defense(rated_hp, int(ac)) or "0"
    offensive_cr = _rating_from_offense(rated_dpr, attack_value, use_save_dc) or "0"

    average = (cr_to_decimal(defensive_cr) + cr_to_decimal(offensive_cr)) / 2
    final_cr = _decimal_to_cr(average)
    row = next(item for item in MONSTER_STATS_BY_CR if item[0] == final_cr)

    return {
        "challenge_rating": final_cr,
        "defensive_cr": defensive_cr,
        "offensive_cr": offensive_cr,
        "proficiency_bonus": row[1],
        "experience_points": XP_BY_CR[final_cr],
        "effective_hp": int(hp),
        "effective_ac": int(ac),
        "damage_per_round": int(damage_per_round),
        "attack_metric": "save_dc" if use_save_dc else "attack_bonus",
        "attack_value": attack_value,
        "clamped": rated_hp != int(hp) or rated_dpr != int(damage_per_round),
    }

"""Authoritative D&D ability-score generation shared by API and agents."""

from __future__ import annotations

import random
from typing import Any, Dict, Iterable, List, Mapping, Optional

from rules_catalog import POINT_BUY_COSTS, RuleCatalog
from roll_capture import dice_context, record_roll


ABILITY_NAMES = (
    "strength",
    "dexterity",
    "constitution",
    "intelligence",
    "wisdom",
    "charisma",
)
ABILITY_GENERATION_METHODS = {"point_buy", "standard_array", "rolled"}


class AbilityScoreService:
    """Generate and validate the three ability methods supported by the builder."""

    def __init__(self, rules_catalog: Optional[RuleCatalog] = None, rng: Optional[random.Random] = None):
        self.rules_catalog = rules_catalog or RuleCatalog()
        self.rng = rng or random.SystemRandom()

    def standard_array(self) -> List[int]:
        configured = self.rules_catalog.data.get("ability_generation", {}).get("standard_array", [])
        values = [int(value) for value in configured]
        if len(values) != len(ABILITY_NAMES):
            raise ValueError("The configured standard array must contain exactly six scores.")
        return sorted(values, reverse=True)

    def point_buy_summary(self, scores: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        config = self.rules_catalog.get_point_buy_config()
        normalized = self._normalize_scores(scores or {name: config["minimum"] for name in ABILITY_NAMES})
        errors: List[str] = []
        spent = 0
        for name in ABILITY_NAMES:
            value = normalized[name]
            if value < config["minimum"] or value > config["maximum"]:
                errors.append(
                    f"{name}={value} is outside the point-buy range "
                    f"{config['minimum']}-{config['maximum']}."
                )
                continue
            if value not in POINT_BUY_COSTS:
                errors.append(f"{name}={value} has no configured point-buy cost.")
                continue
            spent += POINT_BUY_COSTS[value]
        if spent > config["budget"]:
            errors.append(f"Point-buy spend {spent} exceeds budget {config['budget']}.")
        return {
            "scores": normalized,
            "budget": config["budget"],
            "spent": spent,
            "remaining": config["budget"] - spent,
            "minimum": config["minimum"],
            "maximum": config["maximum"],
            "valid": not errors,
            "errors": errors,
        }

    def generate(self, method: str, scores: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        normalized_method = str(method or "").strip().lower()
        if normalized_method not in ABILITY_GENERATION_METHODS:
            raise ValueError(f"Unsupported ability generation method: {method}")

        if normalized_method == "point_buy":
            summary = self.point_buy_summary(scores)
            if not summary["valid"]:
                raise ValueError(" ".join(summary["errors"]))
            return {"method": normalized_method, "pool": [], "rolls": [], "point_buy": summary}

        if normalized_method == "standard_array":
            pool = [
                {"slot_id": f"array-{index + 1}", "score": score, "dice": [], "dropped_index": None}
                for index, score in enumerate(self.standard_array())
            ]
            return {"method": normalized_method, "pool": pool, "rolls": []}

        rolls = [self._roll_four_drop_lowest(index) for index in range(len(ABILITY_NAMES))]
        rolls.sort(key=lambda item: (-item["total"], item["slot_id"]))
        pool = [
            {
                "slot_id": item["slot_id"],
                "score": item["total"],
                "dice": item["dice"],
                "dropped_index": item["dropped_index"],
            }
            for item in rolls
        ]
        return {"method": normalized_method, "pool": pool, "rolls": rolls}

    def validate_rolls(self, scores: Mapping[str, Any], rolls: Iterable[Any]) -> List[str]:
        errors: List[str] = []
        normalized_scores = self._normalize_scores(scores)
        normalized_rolls = list(rolls or [])
        if len(normalized_rolls) != len(ABILITY_NAMES):
            return ["Rolled ability generation requires exactly six recorded rolls."]

        totals: List[int] = []
        for index, roll in enumerate(normalized_rolls, start=1):
            payload = roll.model_dump() if hasattr(roll, "model_dump") else dict(roll or {})
            dice = [int(value) for value in payload.get("dice", [])]
            if len(dice) != 4 or any(value < 1 or value > 6 for value in dice):
                errors.append(f"Ability roll {index} must contain four d6 results.")
                continue
            dropped_index = int(payload.get("dropped_index", -1))
            if dropped_index < 0 or dropped_index >= len(dice) or dice[dropped_index] != min(dice):
                errors.append(f"Ability roll {index} must drop one of its lowest dice.")
                continue
            expected_total = sum(dice) - min(dice)
            recorded_total = int(payload.get("total", expected_total))
            if recorded_total != expected_total:
                errors.append(f"Ability roll {index} total does not match its dice.")
                continue
            totals.append(recorded_total)

        if not errors and sorted(totals) != sorted(normalized_scores.values()):
            errors.append("Assigned ability scores do not match the recorded rolled pool.")
        return errors

    def _roll_four_drop_lowest(self, index: int) -> Dict[str, Any]:
        dice = [self.rng.randint(1, 6) for _ in range(4)]
        dropped_index = dice.index(min(dice))
        kept = [value for offset, value in enumerate(dice) if offset != dropped_index]
        with dice_context(kind="ability", label=f"属性骰池第 {index + 1} 组"):
            record_roll(expression="4d6kh3", dice=dice, kept=kept, modifier=0,
                        total=sum(kept), detail=f"{dice}，去掉第 {dropped_index + 1} 枚")
        return {
            "slot_id": f"roll-{index + 1}",
            "dice": dice,
            "dropped_index": dropped_index,
            "total": sum(dice) - dice[dropped_index],
        }

    @staticmethod
    def _normalize_scores(scores: Mapping[str, Any]) -> Dict[str, int]:
        missing = [name for name in ABILITY_NAMES if name not in scores]
        if missing:
            raise ValueError(f"Missing ability scores: {', '.join(missing)}")
        return {name: int(scores[name]) for name in ABILITY_NAMES}

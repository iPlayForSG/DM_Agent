"""将内部权威记录投影为玩家响应；不改变用于存档和 DM 推理的原始状态。"""

from typing import Any

from fastapi.responses import JSONResponse
from models import RollRecord


def player_payload(value: Any) -> Any:
    hidden_summaries: set[str] = set()

    def hidden(item: dict) -> bool:
        payload = item.get("payload")
        return str(item.get("visibility") or "").strip().casefold() == "hidden" or (
            isinstance(payload, dict) and str(payload.get("visibility") or "").strip().casefold() == "hidden"
        )

    def collect(item: Any) -> None:
        if isinstance(item, dict):
            if hidden(item) and isinstance(item.get("summary"), str):
                hidden_summaries.add(item["summary"])
            for child in item.values():
                collect(child)
        elif isinstance(item, list):
            for child in item:
                collect(child)

    collect(value)
    omitted = object()

    def project(item: Any, field: str = "") -> Any:
        if field == "roll_records" and isinstance(item, list):
            # 用户明确要求在折叠的骰点记录中查看明暗骰；只开放这一经过类型白名单的出口。
            return [RollRecord.model_validate(record).model_dump(mode="json") for record in item]
        if isinstance(item, dict):
            if hidden(item) or (item.get("kind") == "tool_result" and item.get("content") in hidden_summaries):
                return omitted
            return {key: result for key, child in item.items() if (result := project(child, key)) is not omitted}
        if isinstance(item, list):
            return [result for child in item if (result := project(child)) is not omitted]
        return item

    result = project(value)
    return {} if result is omitted else result


class PlayerJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        # REST 使用统一出口，避免加载游戏、traces、局部动作各自遗漏暗骰过滤。
        return super().render(player_payload(content))

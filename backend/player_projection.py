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
        if field == '_dice_replay':
            return omitted
        if field == "roll_records" and isinstance(item, list):
            # 用户明确要求在折叠的骰点记录中查看明暗骰；只开放这一经过类型白名单的出口。
            return [RollRecord.model_validate(record).model_dump(mode="json") for record in item]
        if isinstance(item, dict):
            if hidden(item) or (item.get("kind") == "tool_result" and item.get("content") in hidden_summaries):
                return omitted
            public = {}
            for key, child in item.items():
                # 只转换快照和补丁的保留字段。其它映射中的 "world" 也可能是角色或物品 ID。
                if key == "world" and field == "state_delta":
                    # 私有增量可能只覆盖一个 NPC；玩家以同一响应中的完整见闻刷新，避免误清其余见闻。
                    continue
                if key == "world" and (field == "game_state" or ("game_id" in item and "campaign" in item)):
                    public["known_world"] = [
                        {name: discovery[name] for name in ("id", "title", "summary")}
                        for entry in child["entries"].values() if (discovery := entry.get("discovery"))
                    ]
                elif (result := project(child, key)) is not omitted:
                    public[key] = result
            return public
        if isinstance(item, list):
            return [result for child in item if (result := project(child)) is not omitted]
        return item

    result = project(value)
    return {} if result is omitted else result


class PlayerJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        # REST 使用统一出口，避免加载游戏、traces、局部动作各自遗漏暗骰过滤。
        return super().render(player_payload(content))

"""Measure live DM-loop model calls and latency with disposable in-memory games."""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import DMAgent
from game_logic import GameLogic
from models import AdventureHook, Character, GameState, InventoryItem, Stats, TurnResult

REPORT_DIR = ROOT / "runtime-logs"

# 6f514b4 是单一 DM Brain 重构前的最后一个主 Loop：Director、Specialist、Auditor、Narrator
# 都会调用模型。这里比较的是可由旧图结构证明的最少调用数，不伪造未实测的旧版耗时。
LEGACY_BASELINE_COMMIT = "6f514b4"
LEGACY_MIN_MODEL_CALLS = {
    "ordinary_conversation": 4,
    "state_write_tool": 5,
    "combat_resolution": 6,
}


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def build_eval_character() -> Character:
    return Character(
        name="基准战士",
        class_name="Fighter",
        hp_current=18,
        hp_max=18,
        ac=16,
        stats=Stats(strength=18, dexterity=14, constitution=16),
        inventory=[
            InventoryItem(
                name="Mace",
                quantity=1,
                is_equipped=True,
                type="weapon",
                damage_expression="1d6+4",
                damage_type="bludgeoning",
            )
        ],
    )


def build_eval_state(agent: DMAgent, case_name: str) -> GameState:
    state = agent.create_new_game(
        [build_eval_character()],
        game_id=f"dm-loop-latency-{case_name}-{now_stamp()}",
        title=f"DM Loop Latency {case_name}",
    )
    adventure = AdventureHook(title="断钟回声", summary="完全虚构、只用于 DM Loop 延迟验收的短场景。")
    state.campaign.available_adventures = [adventure]
    state.campaign.selected_adventure_id = adventure.adventure_id
    state.campaign.setup_complete = True
    state.campaign.phase = "exploration"
    state.scene = "exploration"
    return state


def model_call_count(result: TurnResult) -> int:
    trace = result.turn_trace
    if trace is None:
        return 0
    return sum(
        int(node.metadata.get("model_call_count", 0) or 0)
        for node in trace.node_traces
        if node.node_name == "draft_response"
    )


def model_node_count(result: TurnResult) -> int:
    trace = result.turn_trace
    if trace is None:
        return 0
    return sum(1 for node in trace.node_traces if node.node_name == "draft_response")


def tool_round_count(result: TurnResult) -> int:
    trace = result.turn_trace
    if trace is None:
        return 0
    return sum(1 for node in trace.node_traces if node.node_name == "execute_tools")


def tool_names(result: TurnResult) -> List[str]:
    return [item.tool_name for item in result.tool_results]


def initial_turn_profile(result: TurnResult) -> str:
    trace = result.turn_trace
    if trace is None:
        return ""
    for node in trace.node_traces:
        if node.node_name == "route_phase":
            return str(node.metadata.get("turn_profile") or "")
    return trace.turn_profile


def initial_turn_intent(result: TurnResult) -> Dict[str, Any]:
    trace = result.turn_trace
    if trace is None:
        return {}
    for node in trace.node_traces:
        if node.node_name != "route_phase":
            continue
        payload = node.metadata.get("turn_intent", {})
        if isinstance(payload, dict):
            return dict(payload)
    return trace.turn_intent.model_dump(mode="json") if trace.turn_intent else {}


def attempted_tool_names(result: TurnResult) -> List[str]:
    trace = result.turn_trace
    if trace is None:
        return []
    names: List[str] = []
    for node in trace.node_traces:
        if node.node_name != "execute_tools":
            continue
        for item in node.metadata.get("tools", []):
            if isinstance(item, dict):
                tool_name = str(item.get("tool_name") or "").strip()
                if tool_name:
                    names.append(tool_name)
    return list(dict.fromkeys(names))


def validation_issue_summaries(result: TurnResult) -> List[Dict[str, str]]:
    return [
        {
            "validator": item.validator,
            "severity": item.severity,
            "action": item.action,
            "summary": item.summary,
        }
        for item in result.validation_issues
    ]


def contains_any(actual: Iterable[str], expected: Iterable[str]) -> bool:
    return bool(set(actual) & set(expected))


async def run_case(
    agent: DMAgent,
    *,
    case_name: str,
    state: GameState,
    message: str,
    validate: Callable[[TurnResult], Dict[str, bool]],
    expected_tools: Optional[List[set[str]]] = None,
    random_seed: Optional[int] = None,
) -> Dict[str, Any]:
    if random_seed is not None:
        random.seed(random_seed)

    started = time.perf_counter()
    result = await agent.run_turn(state, message)
    elapsed_seconds = round(time.perf_counter() - started, 3)
    actual_tools = tool_names(result)
    checks = validate(result)
    issues: List[str] = []

    if result.turn_status != "completed":
        issues.append(f"turn_status={result.turn_status}")
    if result.turn_trace is None:
        issues.append("missing turn trace")
    if model_call_count(result) <= 0:
        issues.append("trace did not report model calls")
    for aliases in expected_tools or []:
        if not contains_any(actual_tools, aliases):
            issues.append(f"missing expected tool: {'/'.join(sorted(aliases))}")
    for check_name, passed in checks.items():
        if not passed:
            issues.append(f"state check failed: {check_name}")

    legacy_calls = LEGACY_MIN_MODEL_CALLS[case_name]
    current_calls = model_call_count(result)
    reduction_pct = (
        round((legacy_calls - current_calls) * 100 / legacy_calls, 1)
        if current_calls > 0
        else None
    )
    trace = result.turn_trace
    final_turn_intent = trace.turn_intent if trace else None
    return {
        "case": case_name,
        "turn_status": result.turn_status,
        "turn_profile": initial_turn_profile(result),
        "final_turn_profile": trace.turn_profile if trace else "",
        "elapsed_seconds": elapsed_seconds,
        "model_calls": current_calls,
        "model_nodes": model_node_count(result),
        "tool_rounds": tool_round_count(result),
        "tool_names": actual_tools,
        "attempted_tool_names": attempted_tool_names(result),
        "turn_intent": initial_turn_intent(result),
        "final_turn_intent": {
            "turn_type": final_turn_intent.turn_type,
            "reason": final_turn_intent.reason,
            "needs_rules": final_turn_intent.needs_rules,
            "rag_intent": final_turn_intent.rag_intent,
            "suggested_tools": list(final_turn_intent.suggested_tools),
        }
        if final_turn_intent
        else {},
        "response_chars": len(result.response or ""),
        "turn_number": result.game_state.turn_number,
        "state_checks": checks,
        "legacy_min_model_calls": legacy_calls,
        "model_call_reduction_pct": reduction_pct,
        "validation_issue_count": len(result.validation_issues),
        "validation_issues": validation_issue_summaries(result),
        "issues": issues,
    }


async def run_eval() -> Dict[str, Any]:
    # 评估状态必须只活在进程内；真实 provider 仍照常调用，但不污染玩家 JSON、rewind 或 SQLite checkpoint。
    os.environ["LANGGRAPH_CHECKPOINT_MODE"] = "memory"
    os.environ["RAG_AUTO_CONTEXT_RESULTS"] = "0"
    agent = DMAgent()
    try:
        preflight = agent.probe_llm()
        public_preflight = {
            "ready": bool(preflight.get("ready")),
            "provider": str(preflight.get("provider") or ""),
            "status_code": int(preflight.get("status_code") or 0),
            "reason": str(preflight.get("reason") or ""),
        }
        if not public_preflight["ready"]:
            return {
                "blocked": True,
                "preflight": public_preflight,
                "legacy_baseline_commit": LEGACY_BASELINE_COMMIT,
                "cases": [],
                "issues": ["native provider preflight failed"],
            }

        ordinary_state = build_eval_state(agent, "ordinary")
        ordinary = await run_case(
            agent,
            case_name="ordinary_conversation",
            state=ordinary_state,
            message=(
                "我在断钟塔外和守夜人闲谈：‘今晚的风从哪边吹？"
                "你值夜时最常听见什么？’"
            ),
            validate=lambda result: {
                "no_tools": not result.tool_results,
                "turn_advanced_once": result.game_state.turn_number == 1,
            },
        )

        write_state = build_eval_state(agent, "state-write")
        state_write = await run_case(
            agent,
            case_name="state_write_tool",
            state=write_state,
            message=(
                "请调用 record_chapter_progress，把已确认的合成基准章节开场记录为："
                "chapter_title='第一章：断钟前厅'，chapter_number=1，"
                "summary='队伍抵达断钟塔前厅，听见夜间异响。'，completed=false。"
                "完成记录后，用一句简体中文说明队伍已经进入前厅。"
            ),
            expected_tools=[{"record_chapter_progress", "campaign.record_chapter_progress"}],
            validate=lambda result: {
                "chapter_recorded": result.game_state.campaign.current_chapter_number == 1,
                "turn_advanced_once": result.game_state.turn_number == 1,
            },
        )

        combat_state = build_eval_state(agent, "combat")
        logic = GameLogic(combat_state)
        encounter = logic.start_encounter(["木制训练傀儡"], enemy_hp=1, enemy_ac=1)
        attacker = next(
            item for item in encounter.combatants.values() if item.linked_character_id == combat_state.active_character_id
        )
        target = next(item for item in encounter.combatants.values() if item.side == "enemy")
        logic.set_initiative(attacker.combatant_id, 20)
        logic.set_initiative(target.combatant_id, 1)
        combat = await run_case(
            agent,
            case_name="combat_resolution",
            state=combat_state,
            message=(
                "现在是基准战士的回合。请调用 attack_target"
                f"(attacker_ref='{attacker.combatant_id}', target_ref='{target.combatant_id}', "
                "resolution_mode='normal', reason='合成 DM Loop 延迟基准')。"
                "目标失去战斗能力后，继续调用 end_encounter 自动收尾；不要请求玩家确认。"
            ),
            expected_tools=[
                {"attack_target", "combat.attack_target"},
                {"end_encounter", "encounter.end", "encounter.end_encounter"},
            ],
            validate=lambda result: {
                "encounter_closed": not (
                    result.game_state.encounter and result.game_state.encounter.active
                ),
                "turn_advanced_once": result.game_state.turn_number == 1,
            },
            random_seed=20260830,
        )

        cases = [ordinary, state_write, combat]
        issues = [f"{item['case']}: {issue}" for item in cases for issue in item["issues"]]
        return {
            "blocked": False,
            "measurement_scope": (
                "DMAgent.run_turn core graph, including provider and deterministic tools; "
                "excluding HTTP transport and post-commit UI suggestion projection"
            ),
            "preflight": public_preflight,
            "checkpoint_backend": agent.checkpoint_backend,
            "legacy_baseline_commit": LEGACY_BASELINE_COMMIT,
            "cases": cases,
            "issues": issues,
        }
    finally:
        agent.close()


async def main() -> int:
    report = await run_eval()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"dm_loop_latency_eval_{now_stamp()}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "report_path": str(report_path),
                "blocked": report["blocked"],
                "issue_count": len(report["issues"]),
                "cases": report["cases"],
            },
            ensure_ascii=False,
        )
    )
    return 1 if report["blocked"] or report["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

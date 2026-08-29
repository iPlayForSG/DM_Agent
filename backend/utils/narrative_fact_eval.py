"""Evaluate narrative freedom, durable story facts, mechanics, and long-context recall."""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import DMAgent
from models import AdventureHook, Character, ChatMessage, EvidenceRecord, GameState, Stats, TurnResult

REPORT_DIR = ROOT / "runtime-logs"
TOOL_ALIASES = {
    "record_evidence": {"record_evidence", "story.record_evidence"},
    "roll_skill_check": {"roll_skill_check", "check.skill"},
}


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def build_eval_state(agent: DMAgent) -> GameState:
    character = Character(
        name="艾琳",
        class_name="Rogue",
        hp_current=9,
        hp_max=12,
        stats=Stats(dexterity=16, intelligence=14, wisdom=14),
        skill_proficiencies={"Investigation": 1, "Perception": 1},
        major_experiences=["队伍最新决定：先救书记员，不追黑袍人。"],
    )
    state = agent.create_new_game(
        [character],
        game_id=f"narrative-fact-eval-{now_stamp()}",
        title="Narrative Fact Eval",
    )
    adventure = AdventureHook(title="断钟回声", summary="调查断钟塔内的失踪事件与异常钟声。")
    state.campaign.available_adventures = [adventure]
    state.campaign.selected_adventure_id = adventure.adventure_id
    state.campaign.setup_complete = True
    state.campaign.phase = "exploration"
    state.campaign.current_chapter_number = 2
    state.campaign.current_chapter_title = "第二章：西侧回廊"
    state.campaign.current_chapter_summary = "队伍正在断钟塔西侧回廊搜寻失踪的书记员。"
    state.scene = "exploration"

    state.evidence_records.extend(
        EvidenceRecord(title=f"旧线索 {index}", summary="合成旧记录。" + "旧" * 260)
        for index in range(12)
    )
    state.evidence_records.append(
        EvidenceRecord(
            title="西墙冷风",
            summary="第三块石砖后持续渗出冷风，来源尚未解决。",
            location="断钟塔西侧回廊",
            tags=["未解决"],
        )
    )
    state.adventure_log.extend(
        [f"合成旧日志 {index}：" + "旧" * 700 for index in range(7)]
        + [
            "守夜人亲手把门槛下拾到的蓝蜡封片交给艾琳；背面刻痕尚未辨认。",
            "队伍决定先救书记员，不追黑袍人。",
        ]
    )
    state.chat_history = [
        ChatMessage(
            role="assistant" if index % 2 else "user",
            content=f"合成过往闲谈 {index}：" + "噪" * 900,
        )
        for index in range(12)
    ]
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


def tool_names(result: TurnResult) -> List[str]:
    return [item.tool_name for item in result.tool_results]


def has_tool(result: TurnResult, expected: str) -> bool:
    return bool(set(tool_names(result)) & TOOL_ALIASES.get(expected, {expected}))


def prepare_context_metadata(result: TurnResult) -> Dict[str, Any]:
    trace = result.turn_trace
    if trace is None:
        return {}
    for node in reversed(trace.node_traces):
        if node.node_name == "prepare_context":
            return {
                "state_summary_chars": int(node.metadata.get("state_summary_chars", 0) or 0),
                "recent_history_chars": int(node.metadata.get("recent_history_chars", 0) or 0),
                "campaign_memory_chars": int(node.metadata.get("campaign_memory_chars", 0) or 0),
                "truncated_contexts": list(node.metadata.get("truncated_contexts", [])),
            }
    return {}


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


def durable_snapshot(state: GameState) -> Dict[str, Any]:
    return {
        "scene": state.scene,
        "campaign": state.campaign.model_dump(mode="json"),
        "adventure_log": list(state.adventure_log),
        "evidence_records": [item.model_dump(mode="json") for item in state.evidence_records],
        "search_records": [item.model_dump(mode="json") for item in state.search_records],
        "characters": {
            character_id: {
                "hp_current": character.hp_current,
                "inventory": [item.model_dump(mode="json") for item in character.inventory],
                "status_effects": list(character.status_effects),
                "major_experiences": list(character.major_experiences),
            }
            for character_id, character in state.characters.items()
        },
    }


def compact_step(
    label: str,
    result: TurnResult,
    elapsed_seconds: float,
    checks: Dict[str, bool],
) -> Dict[str, Any]:
    return {
        "label": label,
        "turn_status": result.turn_status,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "model_calls": model_call_count(result),
        "tool_names": tool_names(result),
        "response_chars": len(result.response or ""),
        "state_checks": checks,
        "context": prepare_context_metadata(result),
        "validation_issues": validation_issue_summaries(result),
    }


def contains_any(text: str, anchors: Iterable[str]) -> bool:
    return any(anchor in text for anchor in anchors)


async def timed_turn(agent: DMAgent, state: GameState, message: str) -> tuple[TurnResult, float]:
    started = time.perf_counter()
    result = await agent.run_turn(state, message)
    return result, time.perf_counter() - started


async def run_eval() -> Dict[str, Any]:
    # 整个评估只使用合成状态和内存 checkpoint，不写玩家存档、rewind 或共享 SQLite。
    os.environ["LANGGRAPH_CHECKPOINT_MODE"] = "memory"
    os.environ["RAG_AUTO_CONTEXT_RESULTS"] = "0"
    random.seed(20260830)
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
                "steps": [],
                "issues": ["native provider preflight failed"],
            }

        state = build_eval_state(agent)
        reports: List[Dict[str, Any]] = []
        issues: List[str] = []

        before_ephemeral = durable_snapshot(state)
        ephemeral, elapsed = await timed_turn(
            agent,
            state,
            "我靠在西侧回廊的窗边，随口问守夜人：‘今晚塔外的风大吗？’",
        )
        ephemeral_checks = {
            "completed": ephemeral.turn_status == "completed",
            "no_tools": not ephemeral.tool_results,
            "durable_state_unchanged": durable_snapshot(ephemeral.game_state) == before_ephemeral,
        }
        reports.append(compact_step("ephemeral_narration", ephemeral, elapsed, ephemeral_checks))
        state = ephemeral.game_state

        evidence_before = len(state.evidence_records)
        story, elapsed = await timed_turn(
            agent,
            state,
            "我收好守夜人刚交给我的蓝蜡封片，并向他确认这是从门槛下捡到的。",
        )
        story_checks = {
            "completed": story.turn_status == "completed",
            "record_evidence_used": has_tool(story, "record_evidence"),
            "evidence_count_increased": len(story.game_state.evidence_records) > evidence_before,
        }
        reports.append(compact_step("durable_story_fact", story, elapsed, story_checks))
        state = story.game_state

        mechanic, elapsed = await timed_turn(
            agent,
            state,
            "我沿着西墙慢慢摸索，尝试找出第三块石砖后冷风的来源。",
        )
        mechanic_checks = {
            "completed": mechanic.turn_status == "completed",
            "skill_check_used": has_tool(mechanic, "roll_skill_check"),
            "authoritative_tool_result_present": bool(mechanic.tool_results),
        }
        reports.append(compact_step("mechanical_resolution", mechanic, elapsed, mechanic_checks))
        state = mechanic.game_state

        recall, elapsed = await timed_turn(
            agent,
            state,
            "在继续前，请简短复述：我们现在位于哪里、刚才决定优先做什么、还有哪条线索尚未解决？",
        )
        recall_checks = {
            "completed": recall.turn_status == "completed",
            "no_tools": not recall.tool_results,
            "current_scene_recalled": contains_any(recall.response, ["西侧回廊", "西回廊"]),
            "latest_decision_recalled": (
                "书记员" in recall.response
                and contains_any(recall.response, ["先救", "优先", "先去救"])
            ),
            "unresolved_clue_recalled": contains_any(recall.response, ["第三块石砖", "冷风"]),
        }
        reports.append(compact_step("long_context_recall", recall, elapsed, recall_checks))

        for report in reports:
            if report["turn_status"] != "completed":
                issues.append(f"{report['label']}: turn_status={report['turn_status']}")
            for check_name, passed in report["state_checks"].items():
                if not passed:
                    issues.append(f"{report['label']}: state check failed: {check_name}")

        if not any("recent_history" in item["context"].get("truncated_contexts", []) for item in reports):
            issues.append("long context setup did not exercise recent_history truncation")

        return {
            "blocked": False,
            "measurement_scope": (
                "DMAgent.run_turn core graph over synthetic state; no response text or full transcript is stored"
            ),
            "preflight": public_preflight,
            "checkpoint_backend": agent.checkpoint_backend,
            "steps": reports,
            "issues": issues,
        }
    finally:
        agent.close()


async def main() -> int:
    report = await run_eval()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"narrative_fact_eval_{now_stamp()}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "report_path": str(report_path),
                "blocked": report["blocked"],
                "issue_count": len(report["issues"]),
                "steps": report["steps"],
            },
            ensure_ascii=False,
        )
    )
    return 1 if report["blocked"] or report["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

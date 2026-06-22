"""Run a lightweight three-chapter workflow eval against the live DM agent."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adventure_service import generate_initial_adventures
from agent import DMAgent
from game_logic import GameLogic
from models import Character, GameState, InventoryItem, SpellSlot, Spellbook, Stats, TurnResult

REPORT_DIR = ROOT / "runtime-logs"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

TOOL_NAME_ALIASES = {
    "lookup_rules": {"lookup_rules", "knowledge.lookup_rules"},
    "append_adventure_log": {"append_adventure_log", "log.append"},
    "record_evidence": {"record_evidence", "story.record_evidence"},
    "record_search_outcome": {"record_search_outcome", "story.record_search_outcome"},
    "record_chapter_progress": {"record_chapter_progress", "campaign.record_chapter_progress"},
    "cast_spell": {"cast_spell", "magic.cast_spell"},
    "use_item": {"use_item", "inventory.use_item"},
    "roll_skill_check": {"roll_skill_check", "check.skill"},
    "roll_saving_throw": {"roll_saving_throw", "check.saving_throw"},
    "save_monster_template": {"save_monster_template", "monster.save_template", "monster.save_game_template"},
    "attack_target": {"attack_target", "combat.attack_target"},
    "end_encounter": {"end_encounter", "encounter.end", "encounter.end_encounter"},
    "encounter.end_encounter": {"end_encounter", "encounter.end", "encounter.end_encounter"},
}


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def build_eval_character() -> Character:
    return Character(
        name="回放牧师",
        species="Human",
        race="Human",
        background_name="Sage",
        origin_feat="Magic Initiate (Druid)",
        class_name="Cleric",
        level=1,
        hp_current=12,
        hp_max=12,
        ac=16,
        speed=30,
        initiative_bonus=1,
        stats=Stats(
            strength=14,
            dexterity=12,
            constitution=14,
            intelligence=10,
            wisdom=16,
            charisma=10,
        ),
        spells=Spellbook(
            cantrips=["神导术", "圣火术"],
            prepared=["祝福术", "疗伤术", "治愈真言"],
            slots={"1": SpellSlot(total=2, used=0)},
            ability="WIS",
        ),
        inventory=[
            InventoryItem(
                name="Mace",
                quantity=1,
                is_equipped=True,
                type="weapon",
                damage_expression="1d6+2",
                damage_type="bludgeoning",
            ),
            InventoryItem(name="Shield", quantity=1, is_equipped=True, type="armor", armor_class_bonus=2),
            InventoryItem(name="Chain Shirt", quantity=1, is_equipped=True, type="armor", armor_class_bonus=3),
            InventoryItem(name="Holy Symbol", quantity=1, is_equipped=True, type="focus"),
            InventoryItem(name="治疗药水", quantity=1, type="consumable", notes="压力测试用消耗品"),
        ],
        skill_proficiencies={"Insight": 1, "Investigation": 1, "Religion": 1},
        save_proficiencies={"wisdom": True, "charisma": True},
        gold_gp=15,
    )


def select_eval_adventure(state: GameState, preferred_id: str = "adv-the-broken-chapel-bell") -> str:
    if not state.campaign.available_adventures:
        state.campaign.available_adventures = generate_initial_adventures(list(state.characters.values()))

    selected = next(
        (hook for hook in state.campaign.available_adventures if hook.adventure_id == preferred_id),
        state.campaign.available_adventures[0],
    )
    state.campaign.selected_adventure_id = selected.adventure_id
    state.campaign.setup_complete = True
    state.campaign.phase = "exploration"
    state.scene = "exploration"
    state.adventure_log.append(f"Selected adventure: {selected.title}")
    return selected.adventure_id


def run_local_chapter_one_encounter(state: GameState) -> Dict[str, str]:
    logic = GameLogic(state)
    if state.active_character_id:
        logic.update_target_hp(state.active_character_id, -2)
    encounter = logic.start_encounter(["钟楼暴徒"], enemy_hp=8, enemy_ac=10)
    party_combatant = next(
        combatant for combatant in encounter.combatants.values() if combatant.linked_character_id == state.active_character_id
    )
    enemy_combatant = next(combatant for combatant in encounter.combatants.values() if combatant.side == "enemy")
    logic.set_initiative(party_combatant.combatant_id, 20)
    logic.set_initiative(enemy_combatant.combatant_id, 5)
    return {
        "attacker_ref": party_combatant.combatant_id,
        "target_ref": enemy_combatant.combatant_id,
    }


def run_local_chapter_two_encounter(state: GameState) -> Dict[str, str]:
    logic = GameLogic(state)
    encounter = logic.start_encounter(["墓穴守钟者"], enemy_hp=12, enemy_ac=11)
    party_combatant = next(
        combatant for combatant in encounter.combatants.values() if combatant.linked_character_id == state.active_character_id
    )
    enemy_combatant = next(combatant for combatant in encounter.combatants.values() if combatant.side == "enemy")
    logic.set_initiative(party_combatant.combatant_id, 19)
    logic.set_initiative(enemy_combatant.combatant_id, 6)
    return {
        "attacker_ref": party_combatant.combatant_id,
        "target_ref": enemy_combatant.combatant_id,
    }


def run_local_chapter_three_encounter(state: GameState) -> Dict[str, str]:
    logic = GameLogic(state)
    encounter = logic.start_encounter(["裂钟仪式主持者"], enemy_hp=14, enemy_ac=12)
    party_combatant = next(
        combatant for combatant in encounter.combatants.values() if combatant.linked_character_id == state.active_character_id
    )
    enemy_combatant = next(combatant for combatant in encounter.combatants.values() if combatant.side == "enemy")
    logic.set_initiative(party_combatant.combatant_id, 21)
    logic.set_initiative(enemy_combatant.combatant_id, 7)
    return {
        "attacker_ref": party_combatant.combatant_id,
        "target_ref": enemy_combatant.combatant_id,
    }


def wound_character_for_heal_test(state: GameState) -> Dict[str, str]:
    if state.active_character_id:
        GameLogic(state).update_target_hp(state.active_character_id, -5)
    return {}


def wound_character_for_item_test(state: GameState) -> Dict[str, str]:
    if state.active_character_id:
        GameLogic(state).update_target_hp(state.active_character_id, -4)
        return {"user_ref": state.active_character_id}
    return {"user_ref": ""}


@dataclass
class EvalStep:
    label: str
    message: str
    expected_tools: List[str] = field(default_factory=list)
    expected_rag_intent: str = ""
    allow_input_required: bool = False
    resume_message: str = ""
    setup: Optional[Callable[[GameState], Dict[str, str] | None]] = None


class ChapterReplayRunner:
    def __init__(self) -> None:
        self.agent = DMAgent()
        self.state = self.agent.create_new_game(
            [build_eval_character()],
            game_id=f"chapter-eval-{now_stamp()}",
            title="Chapter Replay Eval",
        )
        self.selected_adventure_id = select_eval_adventure(self.state)
        self.preflight = self.agent.probe_llm()
        self.issues: List[str] = []
        self.step_reports: List[Dict[str, Any]] = []
        self.context_refs: Dict[str, str] = {}

    def close(self) -> None:
        self.agent.close()

    async def execute_turn(self, message: str) -> TurnResult:
        if self.state.pending_turn:
            result = await self.agent.resume_turn(self.state, message)
        else:
            result = await self.agent.run_turn(self.state, message)
        self.state = result.game_state
        return result

    @staticmethod
    def _english_leakage(text: str) -> List[str]:
        leaks: List[str] = []
        for token in ("Bless", "Cleric", "radiant", "captured", "Guidance", "Healing Word"):
            if token in text:
                leaks.append(token)
        return leaks

    @staticmethod
    def _tool_names(result: TurnResult) -> List[str]:
        return [tool.tool_name for tool in result.tool_results]

    @staticmethod
    def _expected_tool_aliases(expected: str) -> set[str]:
        return set(TOOL_NAME_ALIASES.get(expected, {expected}))

    def _has_expected_tool(self, expected: str, result: TurnResult) -> bool:
        actual_tool_names = set(self._tool_names(result))
        aliases = self._expected_tool_aliases(expected)
        if actual_tool_names & aliases:
            return True
        if "encounter.end" in aliases:
            return not (result.game_state.encounter and result.game_state.encounter.active)
        return False

    def _clear_active_encounter_for_setup(self, label: str) -> None:
        if not (self.state.encounter and self.state.encounter.active):
            return

        outcome = GameLogic(self.state).finalize_encounter()
        if outcome:
            self.issues.append(f"{label}: setup found stale active encounter and finalized it before continuing")
        else:
            self.issues.append(f"{label}: setup found stale active encounter but could not finalize it")

    def _check_step(self, step: EvalStep, result: TurnResult) -> None:
        for expected in step.expected_tools:
            if not self._has_expected_tool(expected, result):
                self.issues.append(f"{step.label}: missing expected tool `{expected}`")

        if step.expected_rag_intent:
            actual_intent = str(result.rag_metadata.get("intent") or "")
            if actual_intent != step.expected_rag_intent:
                self.issues.append(
                    f"{step.label}: expected rag intent `{step.expected_rag_intent}`, got `{actual_intent or 'none'}`"
                )

        if result.turn_status == "input_required" and not step.allow_input_required:
            self.issues.append(f"{step.label}: unexpected input_required pause")
        if result.turn_status == "failed":
            self.issues.append(f"{step.label}: turn failed")

        if result.turn_trace is None:
            self.issues.append(f"{step.label}: missing turn_trace")
        elif not result.turn_trace.phase:
            self.issues.append(f"{step.label}: trace missing phase")

        leakage = self._english_leakage(result.response)
        if leakage:
            self.issues.append(f"{step.label}: English leakage in response: {', '.join(leakage)}")

        model_error = str(result.rag_metadata.get("model_error") or "")
        if model_error:
            self.issues.append(f"{step.label}: model invocation failed: {model_error}")

    async def run_step(self, step: EvalStep) -> None:
        try:
            setup_refs = None
            if step.setup:
                self._clear_active_encounter_for_setup(step.label)
                setup_refs = step.setup(self.state)
                self.context_refs.update(setup_refs or {})
            message = step.message.format(**{**self.context_refs, **(setup_refs or {})})
            result = await self.execute_turn(message)
            resume_count = 0
            while result.turn_status == "input_required" and resume_count < 5:
                pending_kind = str(result.pending_input.get("kind") or "")
                if pending_kind == "tool_confirmation":
                    resume_message = "确认"
                elif step.resume_message:
                    resume_message = step.resume_message.format(**(setup_refs or {}))
                    self.issues.append(f"{step.label}: required clarification before completion")
                else:
                    break
                resume_count += 1
                result = await self.execute_turn(resume_message)
            self._check_step(step, result)
            self.step_reports.append(
                {
                    "label": step.label,
                    "message": message,
                    "resumed": resume_count > 0,
                    "resume_count": resume_count,
                    "turn_status": result.turn_status,
                    "response": result.response,
                    "tool_names": self._tool_names(result),
                    "rag_metadata": result.rag_metadata,
                    "trace": result.turn_trace.model_dump(mode="json") if result.turn_trace else None,
                }
            )
        except Exception as exc:
            self.issues.append(f"{step.label}: step execution crashed: {exc}")
            self.step_reports.append(
                {
                    "label": step.label,
                    "message": step.message,
                    "error": str(exc),
                }
            )

    async def run(self) -> Dict[str, Any]:
        if not self.preflight.get("ready"):
            detail = str(self.preflight.get("detail") or self.preflight.get("reason") or "unknown")
            self.issues.append(f"llm_preflight: {detail}")
            return self._build_report(blocked=True)

        steps = [
            EvalStep(
                label="chapter1_start",
                message=(
                    "请用简体中文开启第一章。先调用 record_chapter_progress，"
                    "chapter_title='第一章：钟声再起'，chapter_number=1，"
                    "summary='队伍抵达破礼拜堂所在的山坡村庄，开始调查失踪与夜钟。'，completed=false。"
                    "再调用 append_adventure_log 记录村民的第一轮报告，然后简短叙述开场。"
                ),
                expected_tools=["campaign.record_chapter_progress", "append_adventure_log"],
            ),
            EvalStep(
                label="chapter1_investigate",
                message=(
                    "我检查礼拜堂门口，并已经发现三项关键线索：一小堆仪式灰烬、"
                    "只朝向礼拜堂的单向脚印、以及刻有弧线纹路的碎铜片。不要再进行检定；"
                    "请直接用 record_evidence 和 record_search_outcome 保存。"
                ),
                expected_tools=["record_evidence", "record_search_outcome"],
                resume_message="把我刚才调查到的关键线索落库，并用中文简短总结。",
            ),
            EvalStep(
                label="chapter1_encounter_setup",
                setup=run_local_chapter_one_encounter,
                message=(
                    "现在是我的回合。请先对自己施放治愈真言作为附赠动作，"
                    "按规则消耗法术位并简短说明结果。"
                ),
                expected_tools=["cast_spell"],
                resume_message="请完成治愈真言施放，并用中文简短说明。",
            ),
            EvalStep(
                label="chapter1_attack",
                message=(
                    "我继续用本回合主动作制服眼前敌人。请调用 "
                    "attack_target(attacker_ref='{attacker_ref}', target_ref='{target_ref}', attack_bonus=99, "
                    "damage_expression='20', damage_type='radiant', resolution_mode='capture', "
                    "reason='chapter one workflow eval')。如果敌人失去行动能力，结束遭遇。"
                    "全程用简体中文。"
                ),
                expected_tools=["attack_target", "encounter.end_encounter"],
                resume_message="请完成攻击并在敌人失去行动能力后结束遭遇。",
            ),
            EvalStep(
                label="chapter1_complete",
                message=(
                    "请调用 record_chapter_progress，"
                    "chapter_title='第一章：钟声再起'，chapter_number=1，"
                    "summary='队伍在礼拜堂门前发现线索，并制服了袭来的钟楼暴徒。'，completed=true。"
                    "全程用简体中文。"
                ),
                expected_tools=["campaign.record_chapter_progress"],
                resume_message="确认完成第一章记录。",
            ),
            EvalStep(
                label="chapter2_start",
                message=(
                    "请开启第二章，并调用 record_chapter_progress，"
                    "chapter_title='第二章：祭坛下的回声'，chapter_number=2，"
                    "summary='队伍进入礼拜堂地下空间，追查钟声来源与失踪者下落。'，completed=false。"
                    "再用 append_adventure_log 记录新的探索目标。"
                ),
                expected_tools=["campaign.record_chapter_progress", "append_adventure_log"],
            ),
            EvalStep(
                label="chapter2_rules_question",
                message="在继续之前，请简要说明专注在受伤时如何维持。必要时查询规则，用简体中文回答。",
                expected_tools=["lookup_rules"],
            ),
            EvalStep(
                label="chapter2_heal_setup",
                setup=wound_character_for_heal_test,
                message="我先对自己施放疗伤术恢复伤势，请按规则处理，并用简体中文简短说明恢复结果。",
                expected_tools=["cast_spell"],
                resume_message="请按规则完成疗伤术恢复，并用简体中文简短说明。",
            ),
            EvalStep(
                label="chapter2_search",
                message=(
                    "我撬开祭坛后的暗格，里面已经露出泛黄文书、断裂铜铃碎片和失踪者名单。"
                    "请记录证据与搜索结果。"
                ),
                expected_tools=["record_evidence", "record_search_outcome"],
                resume_message="把刚才暗格中的关键发现落库，并用中文简短总结。",
            ),
            EvalStep(
                label="chapter2_encounter_setup",
                setup=run_local_chapter_two_encounter,
                message=(
                    "第二章遭遇开始。先让我进行一次感知系的感知豁免，DC 12。然后调用 "
                    "attack_target(attacker_ref='{attacker_ref}', target_ref='{target_ref}', attack_bonus=99, "
                    "damage_expression='20', damage_type='radiant', resolution_mode='normal', "
                    "reason='chapter two workflow eval')。如果敌人倒下，结束遭遇。"
                    "全程用简体中文。"
                ),
                expected_tools=["roll_saving_throw", "attack_target", "encounter.end_encounter"],
                resume_message="继续完成第二章遭遇：先做感知豁免，再攻击并结束遭遇。",
            ),
            EvalStep(
                label="chapter2_complete",
                message=(
                    "请调用 record_chapter_progress，"
                    "chapter_title='第二章：祭坛下的回声'，chapter_number=2，"
                    "summary='队伍在地下祭坛击败守钟者，确认了钟声背后的仪式痕迹。'，completed=true。"
                    "全程用简体中文。"
                ),
                expected_tools=["campaign.record_chapter_progress"],
                resume_message="确认完成第二章记录。",
            ),
            EvalStep(
                label="chapter3_start",
                message=(
                    "请开启第三章，并调用 record_chapter_progress，"
                    "chapter_title='第三章：裂钟仪式'，chapter_number=3，"
                    "summary='队伍追至旧钟楼顶层，准备阻止午夜裂钟仪式。'，completed=false。"
                    "再用 append_adventure_log 记录最终目标。"
                ),
                expected_tools=["campaign.record_chapter_progress", "append_adventure_log"],
            ),
            EvalStep(
                label="chapter3_item_use",
                setup=wound_character_for_item_test,
                message=(
                    "我喝下一瓶治疗药水稳住伤势。请调用 use_item(user_ref='{user_ref}', "
                    "item_name='治疗药水', quantity=1, reason='第三章压力测试：战前消耗补给')，"
                    "然后用简体中文说明背包里还剩几瓶。"
                ),
                expected_tools=["use_item"],
                resume_message="请完成治疗药水消耗，并用中文说明库存剩余。",
            ),
            EvalStep(
                label="chapter3_evidence",
                message=(
                    "我检查裂钟仪式的铭文和献祭名单，并已经确认仪式条件与幕后主谋。"
                    "请记录证据与搜索结果。"
                ),
                expected_tools=["record_evidence", "record_search_outcome"],
                resume_message="把仪式铭文与名单中的关键发现落库，并用中文简短总结。",
            ),
            EvalStep(
                label="chapter3_final_encounter",
                setup=run_local_chapter_three_encounter,
                message=(
                    "最终遭遇开始。现在是我的回合。不要再消耗任何物品。请调用 "
                    "attack_target(attacker_ref='{attacker_ref}', target_ref='{target_ref}', attack_bonus=99, "
                    "damage_expression='24', damage_type='radiant', resolution_mode='normal', "
                    "reason='chapter three finale workflow eval')。如果敌人倒下，结束遭遇。"
                    "全程用简体中文。"
                ),
                expected_tools=["attack_target", "encounter.end_encounter"],
                resume_message="继续完成最终遭遇：攻击并结束遭遇。",
            ),
            EvalStep(
                label="chapter3_complete",
                message=(
                    "请调用 record_chapter_progress，"
                    "chapter_title='第三章：裂钟仪式'，chapter_number=3，"
                    "summary='队伍阻止裂钟仪式，击败仪式主持者，并确认失踪者线索已闭合。'，completed=true。"
                    "全程用简体中文。"
                ),
                expected_tools=["campaign.record_chapter_progress"],
                resume_message="确认完成第三章记录。",
            ),
        ]

        for step in steps:
            await self.run_step(step)
            if any("model invocation failed" in issue for issue in self.issues[-3:]):
                break

        completed_numbers = [chapter.chapter_number for chapter in self.state.campaign.completed_chapters]
        if completed_numbers != [1, 2, 3]:
            self.issues.append(f"chapter_progress: expected completed chapters [1, 2, 3], got {completed_numbers}")
        active_character = self.state.get_active_char()
        if active_character:
            potion = next((item for item in active_character.inventory if item.name == "治疗药水"), None)
            if not potion:
                self.issues.append("inventory: expected 治疗药水 to remain in inventory with quantity 0")
            elif potion.quantity != 0:
                self.issues.append(f"inventory: expected 治疗药水 quantity 0, got {potion.quantity}")
        if len(self.state.turn_traces) < len(self.step_reports):
            self.issues.append(
                f"trace_history: expected at least {len(self.step_reports)} traces, got {len(self.state.turn_traces)}"
            )
        return self._build_report(blocked=False)

    def _build_report(self, blocked: bool) -> Dict[str, Any]:
        return {
            "blocked": blocked,
            "preflight": self.preflight,
            "game_id": self.state.game_id,
            "selected_adventure_id": self.selected_adventure_id,
            "completed_chapters": [chapter.model_dump(mode="json") for chapter in self.state.campaign.completed_chapters],
            "current_chapter_number": self.state.campaign.current_chapter_number,
            "current_chapter_title": self.state.campaign.current_chapter_title,
            "trace_count": len(self.state.turn_traces),
            "step_reports": self.step_reports,
            "issues": self.issues,
        }


async def main() -> int:
    runner = ChapterReplayRunner()
    try:
        report = await runner.run()
    finally:
        runner.close()

    report_path = REPORT_DIR / f"chapter_replay_eval_{now_stamp()}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"report_path": str(report_path), "issue_count": len(report["issues"])}, ensure_ascii=False))
    for issue in report["issues"]:
        print(f"- {issue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

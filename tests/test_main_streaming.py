import asyncio
import json
import os
import sys
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")
os.environ.setdefault("RAG_AUTO_CONTEXT_RESULTS", "0")

import main as api_main
from game_logic import GameLogic
from models import ActionSuggestion, Character, ChatMessage, GameState, NodeTrace, PendingTurnState, ResourcePool, ToolResult, TurnResult, TurnTrace, ValidationIssue
from turn_stream import emit_turn_stream_event


class FakeStorage:
    def __init__(self, state: GameState | None):
        self.state = state
        self.saved_game_id = None
        self.saved_state = None
        self.rewind_snapshots = {}

    def load_game(self, game_id: str):
        return self.state

    def save_game(self, game_id: str, state: GameState) -> None:
        self.saved_game_id = game_id
        self.saved_state = state
        self.state = state

    def save_rewind_snapshot(self, game_id: str, message_index: int, state: GameState) -> None:
        self.rewind_snapshots[(game_id, message_index)] = state.model_copy(deep=True)

    def load_rewind_snapshot(self, game_id: str, message_index: int):
        snapshot = self.rewind_snapshots.get((game_id, message_index))
        return snapshot.model_copy(deep=True) if snapshot else None

    def prune_rewind_snapshots_from(self, game_id: str, message_index: int) -> None:
        for key in list(self.rewind_snapshots):
            if key[0] == game_id and key[1] >= message_index:
                del self.rewind_snapshots[key]


class FakeAgent:
    def __init__(self, result: TurnResult):
        self.result = result
        self.run_calls = 0
        self.resume_calls = 0
        self.projection_calls = 0
        self.run_inputs = []
        self.checkpoint_backend = "sqlite"
        self.checkpoint_db_path = "backend/Game/langgraph_checkpoints.sqlite"
        self.checkpoint_warning = ""
        self.backend_name = "langgraph"
        self.agent_topology = {"exploration": ["lookup_rules"], "combat": ["attack_target"]}
        self.rag_engine = type(
            "FakeRAG",
            (),
            {
                "is_ready": lambda self: False,
                "status_payload": lambda self: {"ready": False},
            },
        )()

    async def run_turn(self, state: GameState, user_input: str) -> TurnResult:
        self.run_calls += 1
        self.run_inputs.append(user_input)
        return self.result

    async def resume_turn(self, state: GameState, user_input: str) -> TurnResult:
        self.resume_calls += 1
        return self.result

    def project_action_suggestions(self, state: GameState, response: str, user_input: str = ""):
        self.projection_calls += 1
        return (
            [
                ActionSuggestion(label="查看铁栅", action="我查看铁栅上的新鲜刮痕。"),
                ActionSuggestion(label="聆听锁链", action="我贴近铁栅，辨认锁链声来自哪里。"),
                ActionSuggestion(label="检查地面", action="我检查铁栅前的地面，寻找近期活动痕迹。"),
            ],
            {"status": "completed"},
        )

    def close(self) -> None:
        return None

    def llm_runtime_payload(self):
        return {
            "model_name": "fake-model",
            "base_url": "https://example.test/v1",
            "raw_base_url": "https://example.test",
            "base_url_normalized": True,
            "configured": True,
        }

    def probe_llm(self):
        return {
            **self.llm_runtime_payload(),
            "ready": True,
            "status_code": 200,
            "reason": "ok",
            "detail": "ok",
            "probe_url": "https://example.test/v1/models",
        }


class LiveEventFakeAgent(FakeAgent):
    async def run_turn(self, state: GameState, user_input: str) -> TurnResult:
        emit_turn_stream_event("agent.output.delta", {"stage": "dm_model", "text": "先确认现场，"})
        await asyncio.sleep(0.01)
        emit_turn_stream_event("agent.output.delta", {"stage": "dm_model", "text": "再结算行动。"})
        return await super().run_turn(state, user_input)


class BlockingLiveEventFakeAgent(FakeAgent):
    def __init__(self, result: TurnResult):
        super().__init__(result)
        self.live_event_emitted = threading.Event()
        self.release_turn = threading.Event()

    async def run_turn(self, state: GameState, user_input: str) -> TurnResult:
        emit_turn_stream_event("agent.output.delta", {"stage": "dm_model", "text": "实时片段"})
        self.live_event_emitted.set()
        await asyncio.to_thread(self.release_turn.wait, 1)
        return await super().run_turn(state, user_input)


@contextmanager
def patched_runtime(agent_obj, game_storage_obj):
    original_agent = api_main.agent
    original_game_storage = api_main.game_storage
    api_main.agent = agent_obj
    api_main.game_storage = game_storage_obj
    try:
        yield
    finally:
        api_main.agent = original_agent
        api_main.game_storage = original_game_storage


def parse_sse_events(lines):
    events = []
    current = {}
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if not line:
            if current:
                events.append(current)
                current = {}
            continue
        if line.startswith("event: "):
            current["event"] = line[len("event: ") :]
        elif line.startswith("data: "):
            current["data"] = json.loads(line[len("data: ") :])
    if current:
        events.append(current)
    return events


class TurnStreamingApiTests(unittest.TestCase):
    def test_execute_turn_request_forwards_event_before_turn_completes(self) -> None:
        state = GameState(game_id="live-bridge-test", title="Live Bridge Test")
        result = TurnResult(response="Resolved", turn_status="completed", game_state=state.model_copy(deep=True))
        fake_agent = BlockingLiveEventFakeAgent(result)
        received = []

        async def run_scenario():
            task = asyncio.create_task(
                api_main._execute_turn_request(
                    state,
                    "Inspect",
                    stream_event=lambda event, data: received.append((event, data)),
                )
            )
            emitted = await asyncio.to_thread(fake_agent.live_event_emitted.wait, 1)
            self.assertTrue(emitted)
            self.assertFalse(task.done())
            self.assertEqual(received[0][0], "agent.output.delta")
            self.assertEqual(received[0][1]["text"], "实时片段")
            fake_agent.release_turn.set()
            return await task

        original_agent = api_main.agent
        api_main.agent = fake_agent
        try:
            resolved_result, mode = asyncio.run(run_scenario())
        finally:
            fake_agent.release_turn.set()
            api_main.agent = original_agent

        self.assertEqual(mode, "start")
        self.assertEqual(resolved_result.response, "Resolved")

    def test_turn_stream_emits_agent_output_before_result(self) -> None:
        state = GameState(game_id="agent-output-test", title="Agent Output Test")
        result = TurnResult(response="Resolved", turn_status="completed", game_state=state.model_copy(deep=True))
        fake_agent = LiveEventFakeAgent(result)
        fake_storage = FakeStorage(state)

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                with client.stream(
                    "POST",
                    "/api/v1/games/agent-output-test/turns/stream",
                    json={"message": "Inspect"},
                ) as resp:
                    self.assertEqual(resp.status_code, 200)
                    events = parse_sse_events(list(resp.iter_lines()))

        event_names = [event["event"] for event in events]
        self.assertEqual(
            event_names,
            [
                "turn.started",
                "agent.output.delta",
                "agent.output.delta",
                "turn.completed",
                "turn.saved",
                "turn.finished",
            ],
        )
        self.assertLess(event_names.index("agent.output.delta"), event_names.index("turn.completed"))
        self.assertEqual(events[1]["data"]["text"], "先确认现场，")
        self.assertEqual(events[2]["data"]["text"], "再结算行动。")
        self.assertEqual(events[1]["data"]["game_id"], "agent-output-test")

    def test_reply_length_settings_are_persisted(self) -> None:
        state = GameState(game_id="length-test", title="Length Test")
        result = TurnResult(response="unused", turn_status="completed", game_state=state.model_copy(deep=True))
        fake_agent = FakeAgent(result)
        fake_storage = FakeStorage(state)

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                resp = client.post(
                    "/api/v1/games/length-test/reply-length",
                    json={"min_chars": 120, "max_chars": 480},
                )

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["reply_length"], {"min_chars": 120, "max_chars": 480})
        self.assertEqual(fake_storage.saved_state.campaign.reply_min_chars, 120)
        self.assertEqual(fake_storage.saved_state.campaign.reply_max_chars, 480)

    def test_reply_length_settings_reject_inverted_bounds(self) -> None:
        state = GameState(game_id="length-test", title="Length Test")
        result = TurnResult(response="unused", turn_status="completed", game_state=state.model_copy(deep=True))
        fake_agent = FakeAgent(result)
        fake_storage = FakeStorage(state)

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                resp = client.post(
                    "/api/v1/games/length-test/reply-length",
                    json={"min_chars": 500, "max_chars": 100},
                )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("最小字数", resp.json()["detail"])
        self.assertIsNone(fake_storage.saved_state)

    def test_turn_stream_emits_lifecycle_events(self) -> None:
        state = GameState(game_id="stream-test", title="Stream Test")
        result = TurnResult(response="DM reply", turn_status="completed", game_state=state.model_copy(deep=True))
        fake_agent = FakeAgent(result)
        fake_storage = FakeStorage(state)

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                with client.stream("POST", "/api/v1/games/stream-test/turns/stream", json={"message": "Hello"}) as resp:
                    self.assertEqual(resp.status_code, 200)
                    self.assertTrue(resp.headers["content-type"].startswith("text/event-stream"))
                    events = parse_sse_events(list(resp.iter_lines()))

        self.assertEqual([event["event"] for event in events], ["turn.started", "turn.completed", "turn.saved", "turn.finished"])
        self.assertEqual(events[0]["data"]["mode"], "start")
        self.assertEqual(events[1]["data"]["response"], "DM reply")
        self.assertEqual(events[1]["data"]["turn_status"], "completed")
        self.assertEqual(events[1]["data"]["game_id"], "stream-test")
        self.assertEqual(fake_agent.run_calls, 1)
        self.assertEqual(fake_agent.resume_calls, 0)
        self.assertEqual(fake_storage.saved_game_id, "stream-test")

    def test_sync_turn_endpoint_resumes_pending_turn(self) -> None:
        state = GameState(game_id="resume-test", title="Resume Test")
        state.pending_turn = PendingTurnState(
            thread_id="resume-thread",
            prompt="Need more detail",
            original_input="continue",
        )
        resumed_state = state.model_copy(deep=True)
        resumed_state.pending_turn = None
        resumed_state.turn_number = 1
        result = TurnResult(
            response="Resolved",
            turn_status="completed",
            game_state=resumed_state,
        )
        fake_agent = FakeAgent(result)
        fake_storage = FakeStorage(state)

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                resp = client.post("/api/v1/games/resume-test/turns", json={"message": "I inspect the altar."})

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["turn_status"], "completed")
        self.assertEqual(payload["response"], "Resolved")
        self.assertEqual(fake_agent.run_calls, 0)
        self.assertEqual(fake_agent.resume_calls, 1)
        self.assertEqual(fake_storage.saved_game_id, "resume-test")

    def test_delete_message_restores_rewind_snapshot(self) -> None:
        state = GameState(game_id="rewind-test", title="Rewind Test")
        state.chat_history.append(api_main.ChatMessage(role="user", content="旧行动"))
        state.chat_history.append(api_main.ChatMessage(role="assistant", content="旧回应"))
        snapshot = GameState(game_id="rewind-test", title="Rewind Test")
        result = TurnResult(response="unused", turn_status="completed", game_state=state.model_copy(deep=True))
        fake_agent = FakeAgent(result)
        fake_storage = FakeStorage(state)
        fake_storage.save_rewind_snapshot("rewind-test", 0, snapshot)

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                resp = client.post("/api/v1/games/rewind-test/messages/0/delete")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["status"], "rewound")
        self.assertEqual(payload["game_state"]["chat_history"], [])
        self.assertEqual(fake_storage.saved_state.chat_history, [])

    def test_delete_message_clears_pending_turn_from_legacy_rewind_snapshot(self) -> None:
        state = GameState(game_id="legacy-pending-rewind", title="Legacy Pending Rewind")
        state.chat_history.append(api_main.ChatMessage(role="user", content="旧行动"))
        state.chat_history.append(api_main.ChatMessage(role="assistant", content="旧回应"))
        snapshot = GameState(game_id="legacy-pending-rewind", title="Legacy Pending Rewind")
        snapshot.pending_turn = PendingTurnState(
            thread_id="already-consumed-thread",
            kind="player_choice",
            prompt="选择一条路。",
            original_input="旧行动",
        )
        result = TurnResult(response="unused", turn_status="completed", game_state=state.model_copy(deep=True))
        fake_agent = FakeAgent(result)
        fake_storage = FakeStorage(state)
        fake_storage.save_rewind_snapshot("legacy-pending-rewind", 0, snapshot)

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                resp = client.post("/api/v1/games/legacy-pending-rewind/messages/0/delete")

        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(fake_storage.saved_state.pending_turn)
        self.assertIsNone(resp.json()["game_state"]["pending_turn"])

    def test_resume_then_delete_player_message_does_not_revive_pending_turn(self) -> None:
        state = GameState(game_id="resume-rewind", title="Resume Rewind")
        state.chat_history.append(api_main.ChatMessage(role="assistant", content="铁栅后传来声响。"))
        state.pending_turn = PendingTurnState(
            thread_id="single-use-thread",
            kind="player_choice",
            prompt="选择一条路。",
            original_input="我朝声音走去。",
            details={"options": ["走铁栅", "走检修沟"]},
        )
        cancelled_state = state.model_copy(deep=True)
        cancelled_state.pending_turn = None
        cancelled_state.chat_history.append(api_main.ChatMessage(role="user", content="我朝声音走去。"))
        cancelled_state.chat_history.append(api_main.ChatMessage(role="assistant", content="本回合未提交。"))
        result = TurnResult(response="本回合未提交。", turn_status="failed", game_state=cancelled_state)
        fake_agent = FakeAgent(result)
        fake_storage = FakeStorage(state)

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                resume_resp = client.post("/api/v1/games/resume-rewind/turns", json={"message": "暂不决定"})
                delete_resp = client.post("/api/v1/games/resume-rewind/messages/1/delete")

        self.assertEqual(resume_resp.status_code, 200)
        self.assertEqual(fake_agent.resume_calls, 1)
        self.assertEqual(delete_resp.status_code, 200)
        self.assertIsNone(fake_storage.saved_state.pending_turn)
        self.assertEqual([message.content for message in fake_storage.saved_state.chat_history], ["铁栅后传来声响。"])

    def test_rewrite_player_message_restores_snapshot_then_runs_turn(self) -> None:
        state = GameState(game_id="rewrite-test", title="Rewrite Test")
        state.chat_history.append(api_main.ChatMessage(role="user", content="旧行动"))
        state.chat_history.append(api_main.ChatMessage(role="assistant", content="旧回应"))
        snapshot = GameState(game_id="rewrite-test", title="Rewrite Test")
        new_state = snapshot.model_copy(deep=True)
        new_state.chat_history.append(api_main.ChatMessage(role="user", content="新行动"))
        new_state.chat_history.append(api_main.ChatMessage(role="assistant", content="新回应"))
        result = TurnResult(response="新回应", turn_status="completed", game_state=new_state)
        fake_agent = FakeAgent(result)
        fake_storage = FakeStorage(state)
        fake_storage.save_rewind_snapshot("rewrite-test", 0, snapshot)

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                resp = client.post("/api/v1/games/rewrite-test/messages/0/rewrite", json={"message": "新行动"})

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["response"], "新回应")
        self.assertEqual(fake_agent.run_calls, 1)
        self.assertEqual(fake_storage.saved_state.chat_history[-1].content, "新回应")

    def test_rewrite_clears_pending_turn_from_legacy_rewind_snapshot(self) -> None:
        state = GameState(game_id="rewrite-stale-pending", title="Rewrite Stale Pending")
        state.chat_history.append(api_main.ChatMessage(role="user", content="旧行动"))
        state.chat_history.append(api_main.ChatMessage(role="assistant", content="旧回应"))
        snapshot = GameState(game_id="rewrite-stale-pending", title="Rewrite Stale Pending")
        snapshot.pending_turn = PendingTurnState(
            thread_id="already-consumed-thread",
            kind="player_choice",
            prompt="选择一条路。",
            original_input="旧行动",
        )
        rewritten_state = GameState(game_id="rewrite-stale-pending", title="Rewrite Stale Pending")
        rewritten_state.chat_history.append(api_main.ChatMessage(role="user", content="新行动"))
        rewritten_state.chat_history.append(api_main.ChatMessage(role="assistant", content="新回应"))
        result = TurnResult(response="新回应", turn_status="completed", game_state=rewritten_state)
        fake_agent = FakeAgent(result)
        fake_storage = FakeStorage(state)
        fake_storage.save_rewind_snapshot("rewrite-stale-pending", 0, snapshot)

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                resp = client.post(
                    "/api/v1/games/rewrite-stale-pending/messages/0/rewrite",
                    json={"message": "新行动"},
                )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(fake_agent.run_calls, 1)
        self.assertEqual(fake_agent.resume_calls, 0)

    def test_retry_dm_message_restores_pre_player_snapshot_and_reuses_action(self) -> None:
        state = GameState(game_id="retry-test", title="Retry Test")
        state.chat_history.append(api_main.ChatMessage(role="user", content="我检查铁栅。"))
        state.chat_history.append(api_main.ChatMessage(role="assistant", content="模型服务不可用。"))
        snapshot = GameState(game_id="retry-test", title="Retry Test")
        retried_state = snapshot.model_copy(deep=True)
        retried_state.chat_history.append(api_main.ChatMessage(role="user", content="我检查铁栅。"))
        retried_state.chat_history.append(api_main.ChatMessage(role="assistant", content="铁栅后传来锁链声。"))
        result = TurnResult(response="铁栅后传来锁链声。", turn_status="completed", game_state=retried_state)
        fake_agent = FakeAgent(result)
        fake_storage = FakeStorage(state)
        fake_storage.save_rewind_snapshot("retry-test", 0, snapshot)

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                resp = client.post("/api/v1/games/retry-test/messages/1/retry")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["response"], "铁栅后传来锁链声。")
        self.assertEqual(fake_agent.run_inputs, ["我检查铁栅。"])
        self.assertEqual(fake_storage.saved_state.chat_history[-1].content, "铁栅后传来锁链声。")

    def test_retry_rejects_non_dm_message(self) -> None:
        state = GameState(game_id="retry-player", title="Retry Player")
        state.chat_history.append(api_main.ChatMessage(role="user", content="我检查铁栅。"))
        result = TurnResult(response="unused", turn_status="completed", game_state=state.model_copy(deep=True))
        fake_agent = FakeAgent(result)
        fake_storage = FakeStorage(state)

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                resp = client.post("/api/v1/games/retry-player/messages/0/retry")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(fake_agent.run_calls, 0)

    def test_turn_stream_emits_node_trace_events_when_available(self) -> None:
        state = GameState(game_id="node-stream-test", title="Node Stream Test")
        trace = TurnTrace(
            turn_number=1,
            turn_status="completed",
            phase="exploration",
            response="Resolved",
            node_traces=[
                NodeTrace(node_name="plan_turn", summary="Intent planned", metadata={"turn_type": "action_resolution"}),
                NodeTrace(node_name="retrieve_rules", summary="Retrieval skipped", metadata={"intent": "none"}),
            ],
        )
        result = TurnResult(
            response="Resolved",
            turn_status="completed",
            turn_trace=trace,
            game_state=state.model_copy(deep=True),
        )
        fake_agent = FakeAgent(result)
        fake_storage = FakeStorage(state)

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                with client.stream(
                    "POST",
                    "/api/v1/games/node-stream-test/turns/stream",
                    json={"message": "Search the altar"},
                ) as resp:
                    self.assertEqual(resp.status_code, 200)
                    events = parse_sse_events(list(resp.iter_lines()))

        self.assertEqual(
            [event["event"] for event in events],
            ["turn.started", "turn.node", "turn.node", "turn.completed", "turn.saved", "turn.finished"],
        )
        self.assertEqual(events[1]["data"]["node_name"], "plan_turn")
        self.assertEqual(events[1]["data"]["metadata"]["turn_type"], "action_resolution")
        self.assertEqual(events[2]["data"]["node_name"], "retrieve_rules")
        self.assertEqual(events[3]["data"]["turn_trace"]["node_traces"][0]["node_name"], "plan_turn")

    def test_turn_stream_emits_detail_events_from_trace(self) -> None:
        state = GameState(game_id="detail-stream-test", title="Detail Stream Test")
        trace = TurnTrace(
            turn_number=2,
            turn_status="completed",
            phase="exploration",
            response="Resolved",
            rag_metadata={
                "intent": "spell_lookup",
                "reason": "user asked for spell rules",
                "queries": ["Cure Wounds spell"],
                "snippet_count": 3,
                "sources": ["Player Handbook 2024"],
            },
            tool_results=[
                ToolResult(
                    tool_name="roll_dice",
                    summary="Rolled 1d20 -> 14",
                    payload={"expression": "1d20", "total": 14},
                    status="success",
                )
            ],
            validation_notes=["Normalized combat scene."],
            validation_issues=[
                ValidationIssue(
                    validator="combat_phase",
                    severity="warning",
                    action="normalized",
                    summary="Normalized combat scene.",
                    metadata={"phase": "combat"},
                )
            ],
        )
        result = TurnResult(
            response="Resolved",
            turn_status="completed",
            turn_trace=trace,
            game_state=state.model_copy(deep=True),
        )
        fake_agent = FakeAgent(result)
        fake_storage = FakeStorage(state)

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                with client.stream(
                    "POST",
                    "/api/v1/games/detail-stream-test/turns/stream",
                    json={"message": "Check rules"},
                ) as resp:
                    self.assertEqual(resp.status_code, 200)
                    events = parse_sse_events(list(resp.iter_lines()))

        self.assertEqual(
            [event["event"] for event in events],
            [
                "turn.started",
                "rag.completed",
                "tool.completed",
                "validation.note",
                "turn.completed",
                "turn.saved",
                "turn.finished",
            ],
        )
        self.assertEqual(events[1]["data"]["intent"], "spell_lookup")
        self.assertEqual(events[1]["data"]["snippet_count"], 3)
        self.assertEqual(events[1]["data"]["query_count"], 1)
        self.assertEqual(events[2]["data"]["tool_name"], "roll_dice")
        self.assertEqual(events[2]["data"]["payload"]["total"], 14)
        self.assertEqual(events[3]["data"]["note"], "Normalized combat scene.")
        self.assertEqual(events[3]["data"]["validator"], "combat_phase")
        self.assertEqual(events[3]["data"]["severity"], "warning")
        self.assertEqual(events[3]["data"]["action"], "normalized")

    def test_turn_stream_omits_hidden_roll_details(self) -> None:
        state = GameState(game_id="hidden-roll-stream", title="Hidden Roll Stream")
        result = TurnResult(
            response="你没有察觉暗处的变化。",
            turn_status="completed",
            game_state=state.model_copy(deep=True),
            turn_trace=TurnTrace(
                turn_number=1,
                turn_status="completed",
                phase="exploration",
                response="你没有察觉暗处的变化。",
                tool_results=[
                    ToolResult(
                        tool_name="dice.roll",
                        summary="掷骰 1d20: 18 = 18 | 暗中判断伏兵",
                        payload={"expression": "1d20", "total": 18, "visibility": "hidden"},
                    ),
                    ToolResult(
                        tool_name="check.skill",
                        summary="沐瑞安 察觉检定 12 vs DC 10 -> 成功",
                        payload={"actor_name": "沐瑞安", "total": 12},
                    ),
                ],
            ),
        )
        fake_agent = FakeAgent(result)
        fake_storage = FakeStorage(state)

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                with client.stream(
                    "POST",
                    "/api/v1/games/hidden-roll-stream/turns/stream",
                    json={"message": "我查看前方。"},
                ) as resp:
                    self.assertEqual(resp.status_code, 200)
                    events = parse_sse_events(list(resp.iter_lines()))

        tool_events = [event for event in events if event["event"] == "tool.completed"]
        self.assertEqual(len(tool_events), 1)
        self.assertEqual(tool_events[0]["data"]["tool_name"], "check.skill")
        self.assertNotIn("暗中判断伏兵", str(tool_events))

    def test_trace_endpoint_returns_recent_traces(self) -> None:
        state = GameState(game_id="trace-test", title="Trace Test")
        state.turn_traces = [
            TurnTrace(turn_number=1, turn_status="completed", phase="exploration", response="First"),
            TurnTrace(turn_number=2, turn_status="input_required", phase="combat", response="Need target"),
            TurnTrace(turn_number=3, turn_status="completed", phase="combat", response="Resolved"),
        ]
        fake_storage = FakeStorage(state)
        fake_agent = FakeAgent(TurnResult(response="unused", game_state=state.model_copy(deep=True)))

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                resp = client.get("/api/v1/games/trace-test/traces?limit=2")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["game_id"], "trace-test")
        self.assertEqual(payload["trace_count"], 3)
        self.assertEqual(payload["limit"], 2)
        self.assertEqual(len(payload["traces"]), 2)
        self.assertEqual(payload["traces"][0]["turn_number"], 2)
        self.assertEqual(payload["traces"][1]["turn_number"], 3)

    def test_action_suggestions_are_saved_on_the_reply_and_reused(self) -> None:
        state = GameState(game_id="suggestion-cache-test", title="Suggestion Cache Test", turn_number=4)
        state.scene = "exploration"
        state.campaign.phase = "exploration"
        state.chat_history.extend(
            [
                ChatMessage(role="user", content="我检查铁栅。"),
                ChatMessage(role="assistant", content="铁栅后传来缓慢的锁链声。"),
            ]
        )
        fake_storage = FakeStorage(state)
        fake_agent = FakeAgent(TurnResult(response="unused", game_state=state.model_copy(deep=True)))

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                generated = client.post("/api/v1/games/suggestion-cache-test/action-suggestions")
                cached = client.post("/api/v1/games/suggestion-cache-test/action-suggestions")
                reloaded = client.get("/api/v1/games/suggestion-cache-test")

        self.assertEqual(generated.status_code, 200)
        self.assertEqual(generated.json()["metadata"]["status"], "completed")
        self.assertTrue(generated.json()["generated"])
        self.assertEqual(cached.status_code, 200)
        self.assertEqual(cached.json()["metadata"]["status"], "cached")
        self.assertEqual(fake_agent.projection_calls, 1)
        saved_reply = fake_storage.saved_state.chat_history[-1]
        self.assertTrue(saved_reply.action_suggestions_generated)
        self.assertEqual(len(saved_reply.action_suggestions), 3)
        reloaded_reply = reloaded.json()["chat_history"][-1]
        self.assertTrue(reloaded_reply["action_suggestions_generated"])
        self.assertEqual(len(reloaded_reply["action_suggestions"]), 3)

    def test_use_feature_action_endpoint_uses_inferred_feature_metadata(self) -> None:
        state = GameState(game_id="feature-api-test", title="Feature Api Test")
        character = Character(name="凯德", class_name="Fighter")
        character.resources["Second Wind"] = ResourcePool(current_value=1, max_value=1)
        state.characters[character.character_id] = character
        state.active_character_id = character.character_id
        logic = GameLogic(state)
        logic.start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)
        party_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.linked_character_id == character.character_id
        )
        enemy_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.side == "enemy"
        )
        logic.set_initiative(party_combatant.combatant_id, 18)
        logic.set_initiative(enemy_combatant.combatant_id, 8)
        fake_storage = FakeStorage(state)
        fake_agent = FakeAgent(TurnResult(response="unused", game_state=state.model_copy(deep=True)))

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                options_resp = client.get("/api/v1/games/feature-api-test/action-options")
                action_resp = client.post(
                    "/api/v1/games/feature-api-test/actions/use-feature",
                    json={
                        "actor_ref": character.character_id,
                        "feature_name": "Second Wind",
                    },
                )

        self.assertEqual(options_resp.status_code, 200)
        actor = next(item for item in options_resp.json()["actors"] if item["ref"] == character.character_id)
        self.assertEqual(actor["features"][0]["name"], "Second Wind")
        self.assertEqual(actor["features"][0]["action_cost"], "bonus_action")
        self.assertEqual(action_resp.status_code, 200)
        payload = action_resp.json()
        self.assertEqual(payload["tool_result"]["payload"]["action_cost"], "bonus_action")
        self.assertEqual(payload["tool_result"]["payload"]["resource_after"], 0)
        self.assertEqual(fake_storage.saved_game_id, "feature-api-test")
        self.assertEqual(fake_storage.saved_state.characters[character.character_id].resources["Second Wind"].current_value, 0)
        self.assertTrue(fake_storage.saved_state.encounter.turn_bonus_action_used)

    def test_llm_health_endpoint_exposes_probe_payload(self) -> None:
        state = GameState(game_id="health-test", title="Health Test")
        fake_storage = FakeStorage(state)
        fake_agent = FakeAgent(TurnResult(response="unused", game_state=state.model_copy(deep=True)))

        with patched_runtime(fake_agent, fake_storage):
            with TestClient(api_main.app) as client:
                resp = client.get("/api/v1/health/llm")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload["ready"])
        self.assertTrue(payload["base_url_normalized"])
        self.assertEqual(payload["probe_url"], "https://example.test/v1/models")


class MonsterActionParsingTests(unittest.TestCase):
    def test_parse_2024_chinese_attack_action(self) -> None:
        parsed = api_main._parse_monster_action(
            "近战或远程攻击：+6，触及5尺或射程120尺。命中：16（3d8+3）力场伤害。"
        )

        self.assertEqual(parsed["attack_bonus"], 6)
        self.assertEqual(parsed["damage_expression"], "3d8+3")
        self.assertEqual(parsed["damage_type"], "force")

    def test_parse_2024_chinese_attack_check_action(self) -> None:
        parsed = api_main._parse_monster_action(
            "近战攻击检定：+11，触及10尺。命中：13（2d6+6）挥砍伤害外加4（1d8）强酸伤害。"
        )

        self.assertEqual(parsed["attack_bonus"], 11)
        self.assertEqual(parsed["damage_expression"], "2d6+6")
        self.assertEqual(parsed["damage_type"], "slashing")


if __name__ == "__main__":
    unittest.main()

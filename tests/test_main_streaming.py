import json
import os
import sys
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
from models import Character, GameState, NodeTrace, PendingTurnState, ResourcePool, ToolResult, TurnResult, TurnTrace, ValidationIssue


class FakeStorage:
    def __init__(self, state: GameState | None):
        self.state = state
        self.saved_game_id = None
        self.saved_state = None

    def load_game(self, game_id: str):
        return self.state

    def save_game(self, game_id: str, state: GameState) -> None:
        self.saved_game_id = game_id
        self.saved_state = state
        self.state = state


class FakeAgent:
    def __init__(self, result: TurnResult):
        self.result = result
        self.run_calls = 0
        self.resume_calls = 0
        self.checkpoint_backend = "sqlite"
        self.checkpoint_db_path = "backend/Game/langgraph_checkpoints.sqlite"
        self.checkpoint_warning = ""
        self.backend_name = "langgraph"
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
        return self.result

    async def resume_turn(self, state: GameState, user_input: str) -> TurnResult:
        self.resume_calls += 1
        return self.result

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


if __name__ == "__main__":
    unittest.main()

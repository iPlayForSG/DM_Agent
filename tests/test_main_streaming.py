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
from models import GameState, PendingTurnState, TurnResult


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

    async def run_turn(self, state: GameState, user_input: str) -> TurnResult:
        self.run_calls += 1
        return self.result

    async def resume_turn(self, state: GameState, user_input: str) -> TurnResult:
        self.resume_calls += 1
        return self.result

    def close(self) -> None:
        return None


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


if __name__ == "__main__":
    unittest.main()

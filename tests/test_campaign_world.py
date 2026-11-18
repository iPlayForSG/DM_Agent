import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("DM_AGENT_SKIP_DOTENV", "1")
os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import ValidationError

import main as api
import storage
from agent_tools import AgentToolService
from agents.specs import PHASE_CAPABILITY_TOOL_NAMES
from dm_graph import DMGraphRunner
from models import EvidenceRecord, GameState
from player_projection import player_payload
import test_dm_loop_acceptance as acceptance
from world_state import WORLD_TOOLS


CLOCK = {"kind": "clock", "title": "黑钟仪式", "summary": "第三声钟响时密门关闭。", "segments": 3, "trigger": "祭司点燃一支黑烛。"}
NPC = {"kind": "npc", "title": "密探鸦羽", "summary": "渡船人受雇监视码头。", "motive": "替黑钟会寻找失踪的账本。", "attitude": "戒备"}
PRIVATE_ID = "spy-for-black-bell"
PUBLIC = {"title": "渡船人", "summary": "渡船人同意在日落前等候。"}


def call(name, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{name}"}])


class StreamingModel(acceptance.RecordingModel):
    def stream(self, messages):
        yield self.invoke(messages)


class CampaignWorldTests(unittest.TestCase):
    def setUp(self):
        self.state = acceptance.DMLoopAcceptanceTests.build_state()
        self.service = AgentToolService(None, None, None)
        self.runner = DMGraphRunner(acceptance.DisabledRAG(), tool_service=self.service, enable_model=True, checkpoint_mode="memory")
        self.addCleanup(self.runner.close)

    def record(self, key, fact):
        result = self.service.record_world_entry(self.state, entry_id=key, fact=fact, basis="本章设定")
        self.assertTrue(result.ok, result.error)

    def test_schema_links_discovery_and_lookup_are_independent(self):
        self.assertEqual(GameState.model_validate({"schema_version": 4}).world.entries, {})
        self.assertEqual(GameState.model_validate({}).schema_version, 5)
        self.record("dock", {"kind": "location", "title": "码头", "summary": "码头今夜封锁。"})
        self.record("ritual", CLOCK)
        self.record(PRIVATE_ID, {**NPC, "links": ["dock", "ritual"]})
        self.record("cipher", {"kind": "secret", "title": "暗号", "summary": "钟声是开门信号。"})
        evidence = EvidenceRecord(title="纸条", summary="纸上有三个墨点。")
        self.state.evidence_records.append(evidence)
        self.record("letter", {"kind": "clue", "title": "纸条线索", "summary": evidence.summary,
                               "links": ["cipher"], "evidence_id": evidence.evidence_id})
        self.record("missing", {"kind": "quest", "title": "失踪的水手", "summary": "找到离船的三人。", "status": "open"})
        self.assertEqual(player_payload(self.state.model_dump())["known_world"], [])
        self.assertTrue(self.service.reveal_world_entry(self.state, entry_id=PRIVATE_ID, **PUBLIC).ok)
        known = player_payload(self.state.model_dump())["known_world"]
        self.record(PRIVATE_ID, {**NPC, "attitude": "信任"})
        self.assertEqual(player_payload(self.state.model_dump())["known_world"], known)
        self.assertEqual(set(known[0]), {"id", "title", "summary"})
        before = self.state.model_dump()
        found = self.service.lookup_world_entry(self.state, query=PUBLIC["title"]).payload
        self.assertEqual(found["entries"][PRIVATE_ID]["fact"]["links"], ["dock", "ritual"])
        self.assertEqual(self.state.model_dump(), before)
        prompt = self.runner._prepare_context({"game_state": before, "user_input": "再问问渡船人"})["instruction"]
        self.assertIn(NPC["motive"], prompt)
        self.assertIn(CLOCK["trigger"], prompt)
        self.assertEqual(GameState.model_validate_json(self.state.model_dump_json()).world, self.state.world)

    def test_invalid_writes_leave_whole_state_intact(self):
        self.record("ritual", CLOCK)
        args = {"entry_id": "ritual", "expected_progress": 0, "steps": 2, "basis": "两支黑烛点燃"}
        self.assertTrue(self.service.advance_world_clock(self.state, **args).ok)
        before = self.state.model_dump()
        attempts = [
            ("advance_world_clock", args),
            ("advance_world_clock", {**args, "expected_progress": 2}),
            ("advance_world_clock", {**args, "expected_progress": 2, "steps": -1}),
            ("record_world_entry", {"entry_id": "ritual", "fact": NPC}),
            ("record_world_entry", {"entry_id": "ritual", "fact": {**CLOCK, "segments": 4}}),
            ("record_world_entry", {"entry_id": "other", "fact": {**NPC, "links": ["missing"]}}),
            ("record_world_entry", {"entry_id": "other", "fact": {**NPC, "actor_id": "invented"}}),
            ("record_world_entry", {"entry_id": "other", "fact": {**CLOCK, "progress": 3}}),
            ("reveal_world_entry", {"entry_id": "missing", **PUBLIC}),
        ]
        for name, params in attempts:
            if name == "record_world_entry":
                params["basis"] = "章节设定"
            with self.subTest(name=name, args=params):
                self.assertFalse(getattr(self.service, name)(self.state, **params).ok)
                self.assertEqual(self.state.model_dump(), before)
        before["world"]["entries"]["ritual"]["progress"] = 4
        with self.assertRaises(ValidationError):
            GameState.model_validate(before)
        for phase in ("character_creation", "adventure_selection", "level_up"):
            self.assertFalse(set(WORLD_TOOLS).intersection(PHASE_CAPABILITY_TOOL_NAMES[phase]))

    def test_staged_reveal_is_rolled_back_on_cancel_and_on_model_failure(self):
        self.record(PRIVATE_ID, NPC)
        for cancel in (True, False):
            with self.subTest(cancel=cancel):
                responses = [call("reveal_world_entry", entry_id=PRIVATE_ID, **PUBLIC)]
                if cancel:
                    responses.append(call("request_player_choice", prompt="你去码头还是灯塔？", options=["码头", "灯塔"]))
                self.runner._model = acceptance.RecordingModel(responses)
                result = self.runner.run_turn(self.state, "我向守卫打听旧塔。")
                if cancel:
                    self.assertEqual(result.turn_status, "input_required")
                    self.assertEqual(result.state_delta, {})
                    self.assertNotIn(PUBLIC["summary"], str(player_payload(result.model_dump())))
                    result = self.runner.resume_turn(result.game_state, "暂不决定")
                self.assertEqual(result.turn_status, "failed")
                self.assertEqual(result.game_state.world, self.state.world)
                self.assertEqual(result.state_delta, {})

    def test_failed_world_write_cannot_be_narrated_as_success(self):
        self.record("ritual", CLOCK)
        self.runner._model = acceptance.RecordingModel([
            call("advance_world_clock", entry_id="ritual", expected_progress=0, steps=1, basis="第一支蜡烛"),
            call("advance_world_clock", entry_id="ritual", expected_progress=0, steps=1, basis="重复尝试"),
            AIMessage(content="钟已经敲了两次。"),
        ])
        result = self.runner.run_turn(self.state, "我向守卫打听旧塔。")
        self.assertEqual(result.turn_status, "failed")
        self.assertEqual(result.game_state.world, self.state.world)
        self.assertEqual(result.state_delta, {})

    def test_http_stream_save_reload_and_rewind(self):
        self.runner._model = StreamingModel([
            call("record_world_entry", entry_id=PRIVATE_ID, fact=NPC, basis="渡船人的旧雇主"),
            call("reveal_world_entry", entry_id=PRIVATE_ID, **PUBLIC),
            AIMessage(content=PUBLIC["summary"]),
        ])
        with tempfile.TemporaryDirectory() as tmp, patch.object(storage, "GAME_DIR", tmp), \
                patch.object(storage, "REWIND_DIR", str(Path(tmp) / "rewind")):
            games = storage.GameStorage()
            games.save_game(self.state.game_id, self.state)
            url = "/api/v1/games/" + self.state.game_id
            with patch.object(api, "game_storage", games), patch.object(api.agent, "dm_graph_runner", self.runner), TestClient(api.app) as client:
                stream = client.post(url + "/turns/stream", json={"message": "我向守卫打听旧塔。"})
                self.assertEqual(stream.status_code, 200)
                self.assertIn("event: turn.completed", stream.text)
                self.assertIn(PUBLIC["title"], stream.text)
                snapshot = client.get(url).json()
                self.assertEqual(snapshot["known_world"][0]["summary"], PUBLIC["summary"])
                self.assertNotIn("world", snapshot)
                traces = client.get(url + "/traces").json()
                for result in (stream.text, json.dumps(snapshot, ensure_ascii=False), json.dumps(traces, ensure_ascii=False)):
                    for private in (PRIVATE_ID, NPC["motive"], NPC["title"]):
                        self.assertNotIn(private, result)
                self.assertEqual(games.load_game(self.state.game_id).world.entries[PRIVATE_ID].fact.motive, NPC["motive"])
                rewind = client.post(url + "/messages/0/delete")
                self.assertEqual(rewind.status_code, 200)
                self.assertEqual(rewind.json()["game_state"]["known_world"], [])
                self.assertEqual(games.load_game(self.state.game_id).world.entries, {})

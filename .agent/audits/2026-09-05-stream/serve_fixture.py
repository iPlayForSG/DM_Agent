"""真实生产 API + Codex 模型的隔离浏览器验收，所有游戏文件位于临时目录。"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


def main():
    with tempfile.TemporaryDirectory(prefix="dm-stream-browser-") as directory:
        for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE", "LLM_PROFILES_B64", "LLM_ACTIVE_PROFILE_ID", "LLM_CLI_COMMAND"):
            os.environ.pop(key, None)
        os.environ.update({
            "DM_AGENT_SKIP_DOTENV": "1", "LLM_PROVIDER": "codex-cli", "LLM_MODEL": "gpt-5.6-terra",
            "LLM_REASONING_EFFORT": "high", "LANGGRAPH_CHECKPOINT_MODE": "memory", "RAG_RETRIEVAL_MODE": "lexical",
            "RAG_AUTO_CONTEXT_RESULTS": "0", "RAG_SOURCE_ROOT": directory + "/rules", "RAG_LEXICAL_ROOT": directory + "/index",
        })
        sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tests")]
        import storage
        storage.GAME_DIR = directory + "/games"
        storage.REWIND_DIR = directory + "/rewind"
        storage.CHAR_DIR = directory + "/characters"
        storage.MONSTER_DIR = directory + "/monsters"
        import main as api
        import test_dm_graph_workflow as fixtures
        from models import ChatMessage, SessionEvent
        from game_logic import GameLogic
        from roll_capture import capture_rolls, settle_rolls
        import uvicorn

        state = fixtures.DMGraphWorkflowTests()._build_state(with_selected_adventure=True)
        state.game_id = "stream-ui-demo"
        state.title = "流式与骰点合成验收"
        state.campaign.reply_min_chars = 0
        state.campaign.reply_max_chars = 0
        with capture_rolls() as capture, patch("game_logic.random.randint", side_effect=[14, 5]):
            GameLogic(state).roll_skill_check(state.active_character_id, "Stealth", 3, 12)
            api.agent.tool_service.roll_dice(state, "1d20", "察觉门后动静", "hidden")
        state.chat_history = [
            ChatMessage(role="user", content="我检查门闩并推门。"),
            ChatMessage(role="assistant", content="门闩轻轻松开，塔内传来回声。", roll_records=settle_rolls(capture.records, "completed"),
                        roll_records_recorded=True, action_suggestions_generated=True),
        ]
        state.timeline = [SessionEvent(type="assistant_response", summary="合成验收", payload={"turn_status": "completed"})]
        api.game_storage.save_game(state.game_id, state)
        api.agent.project_action_suggestions = lambda *_args: ([], {"status": "fixture"})
        server = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning"))

        @api.app.post("/__smoke/shutdown")
        async def shutdown():
            server.should_exit = True
            return {"ok": True}

        print("Synthetic fixture server ready", flush=True)
        server.run()


if __name__ == "__main__":
    main()

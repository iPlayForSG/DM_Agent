"""隔离玩家数据和凭据的后端审计入口；只输出测试结果与合成复现摘要。"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="dm-backend-audit-") as directory:
        sandbox = Path(directory)
        # 测试进程不继承游戏模型凭据，也不装载真实规则语料或玩家 JSON。
        for name in ("OPENAI_API_KEY", "OPENAI_API_BASE", "OPENAI_BASE_URL", "LLM_MODEL",
                     "LLM_REASONING_EFFORT", "LLM_PROVIDER", "LLM_CLI_COMMAND",
                     "LLM_ACTIVE_PROFILE_ID", "LLM_PROFILES_B64"):
            os.environ.pop(name, None)
        os.environ.update({
            "DM_AGENT_SKIP_DOTENV": "1",
            "DM_AGENT_RUN_CODEX_CLI_STREAM_TEST": "0",
            "LANGGRAPH_CHECKPOINT_MODE": "memory",
            "RAG_AUTO_CONTEXT_RESULTS": "0",
            "RAG_RETRIEVAL_MODE": "lexical",
            "RAG_SOURCE_ROOT": str(sandbox / "rules-source"),
            "RAG_LEXICAL_ROOT": str(sandbox / "rules-index"),
            "RAG_VECTOR_DB_PATH": str(sandbox / "vectors"),
        })
        sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tests")]
        import storage
        storage.GAME_DIR = str(sandbox / "games")
        storage.REWIND_DIR = str(sandbox / "rewind")
        storage.CHAR_DIR = str(sandbox / "characters")
        if "--baseline" in sys.argv:
            suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
        else:
            from repro_findings import AuditReproductions
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(AuditReproductions)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        # main 的 runner 使用内存 checkpoint；这里释放导入时创建的本地资源。
        if "main" in sys.modules:
            sys.modules["main"].agent.close()
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

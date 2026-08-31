# 开发命令

更新时间：2026-08-30。

## 安装与启动

```powershell
# 后端依赖；依据 backend/requirements.txt
python -m pip install -r backend/requirements.txt

# 前端依赖；依据 frontend/package.json
Set-Location frontend
npm install

# Windows 一键启动；依据 start.cmd 和 README.md
Set-Location ..
.\start.cmd
```

`start.cmd` 会选择 Python、探测可用端口、启动 Uvicorn/Vite、写 `backend/runtime-logs/` 和 `frontend/.env.development.local`，并在非 `-ExitOnReady` 模式打开浏览器。

macOS/Linux 使用 Python 3.10+；脚本优先仓库 `.venv`，也接受 `DM_AGENT_PYTHON`：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
(cd frontend && npm install)
./start.sh
```

手工启动：

```powershell
Set-Location backend
python -m uvicorn main:app --host 127.0.0.1 --port 23333 --reload

Set-Location ..\frontend
npm run dev
```

## 验证

先激活已安装 `backend/requirements.txt` 的 Python 环境。当前开发机可使用 `start.cmd` 选择的项目 Conda 环境；不要把开发机绝对路径写进公共文档。

```powershell
# 全量后端测试
python -m unittest discover -s tests -v

# 目标测试示例
python -m unittest tests.test_dm_graph_workflow -v
python -m unittest tests.test_main_streaming -v

# Hook 测试
python -m unittest discover -s .codex/hooks/tests -v

# 前端
Set-Location frontend
npm run build
npm run lint

# 仓库
Set-Location ..
git diff --check
git status --short --branch
```

## 数据导入

从本地 5e.tools 数据目录增量补齐建卡目录（幂等，只追加缺失条目）：

```powershell
Set-Location backend
python utils/import_5etools_builder_options.py --source "E:/5e Tools/data" --dry-run
python utils/import_5etools_builder_options.py --source "E:/5e Tools/data"
```

## DM Loop 真实模型验收

以下命令调用当前已配置的原生 provider，以纯合成状态测量普通对话、确定性章节写入和战斗收尾。评估强制使用内存 checkpoint，不写玩家存档或共享 SQLite；报告写入被忽略的 `backend/runtime-logs/`。

```powershell
python backend/utils/dm_loop_latency_eval.py
python backend/utils/narrative_fact_eval.py
```

第一条报告耗时范围是 `DMAgent.run_turn` 核心图（含 provider 与确定性工具），不含 HTTP 传输和提交后 UI suggestions 投影。第二条验证即时描写、命名线索持久化、机械检定和长上下文回忆；只输出指标与布尔检查，不保存完整回复或 transcript。

## RAG 语料与可选向量索引

运行时默认 `RAG_RETRIEVAL_MODE=lexical`，只读取规范化词法语料，不加载 embedding。以下向量构建命令依据 `README.md` 与 `backend/rag_ingest.py`，依赖未提交的本地规则资料和 GGUF embedding 模型；构建后仍需显式设置 `RAG_RETRIEVAL_MODE=vector` 才会让运行时优先使用向量索引。

```powershell
Set-Location backend

# 可选向量构建；默认写入 Knowledge/vector_db
$env:PYTHONNOUSERSITE="1"
$env:RAG_EMBEDDING_DEVICE="cuda"
python rag_ingest.py --reset

# 只验证切片，不加载 embedding 或写入 Chroma
$env:PYTHONNOUSERSITE="1"
python rag_ingest.py --dry-run

# CPU 环境仅做有限 smoke；输出使用独立目录和 collection
$env:PYTHONNOUSERSITE="1"
python rag_ingest.py --max-chunks 2 --reset --db-path Knowledge/vector_db_smoke --collection rag_smoke
```

原始规则书变化后先生成跨平台词法语料：

```sh
python backend/utils/normalize_rule_documents.py
```

## 已验证状态

2026-07-26 在当前工作树实际执行：

- 后端 `unittest`：**159 tests**，成功（项目 Conda 环境）。
- 项目记忆 Hook `unittest`：20 tests，成功。
- `npm run build`：成功。
- `npm run lint`：0 errors、2 warnings；警告位于 `App.jsx` 的 Hook dependency。
- `git diff --check`：干净。

2026-08-28 实际执行项目记忆 Hook `unittest`：25 tests，成功。

2026-08-28 当前功能分支实际执行：CLI/RAG/规范化目标测试 10 个成功；macOS `start.sh` 与 health/config/RAG status smoke 成功；Codex/Claude Code 真实结构化文本调用成功，Codex 真实应用工具调用成功；前端 build 成功、lint 0 errors/2 warnings。全量后端 169 个测试中 13 个失败，原因是当前 Mac 缺少 ignored `backend/data/spells.json`，相关法术/建卡 fixture 无法解析，不是本分支行为回归。

浏览器交互长流程与本地 GGUF/Metal 向量查询尚未完成，不能标为已验证。

2026-08-30 `refactor/agent_loop` 实际执行：最终完整后端 196 项全部成功；`python -m compileall -q backend` 与前端 build 成功；lint 0 errors/2 条既有 Hook dependency warning；`git diff --check` 通过，仅有 LF/CRLF 工作区提示。原生 provider 的核心 Loop 三类矩阵与叙事事实四步验收报告 issue 均为 0。

2026-08-30 Codex 默认传输变更实际执行：本机 `codex-cli 0.147.0` 通过 `gpt-5.6-terra` / `high` 真实调用；项目 `CodingAgentCLIChatModel` 结构化 smoke 返回预期文本且无工具调用。完整后端 199 项成功，前端 build 成功，lint 0 errors/2 条既有 Hook dependency warning。

2026-08-30 词法检索默认化实际执行：本机规范化语料 smoke 报告 `retrieval_mode=lexical`、`backend=lexical-grep`、`vector_ready=false`、无 vector error/fallback，并返回规则结果；RAG 目标测试 10 项、完整后端 200 项成功。前端 build 成功，lint 0 errors/2 条既有 Hook dependency warning。

## 当前不存在的命令

仓库未定义独立 formatter、Python/JS 类型检查、数据库 migration 或代码生成脚本。新增这些门禁时，应同步 `AGENTS.md`、本文件和相关 CI。

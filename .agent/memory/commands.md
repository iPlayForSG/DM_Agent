# 开发命令

更新时间：2026-08-28。

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

## RAG 索引构建

以下命令依据 `README.md` 与 `backend/rag_ingest.py`。它们依赖未提交的本地规则资料和 GGUF embedding 模型；2026-08-28 本次记忆系统审计未执行。

```powershell
Set-Location backend

# 正式构建；默认写入 Knowledge/vector_db
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

## 当前不存在的命令

仓库未定义独立 formatter、Python/JS 类型检查、数据库 migration 或代码生成脚本。新增这些门禁时，应同步 `AGENTS.md`、本文件和相关 CI。

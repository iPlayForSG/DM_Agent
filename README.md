# DM_Agent

DM_Agent 是一个本地优先的 D&D 2024 单人跑团 DM Agent 原型。项目通过 FastAPI 后端、React/Vite 前端、LangGraph 编排层，以及一组确定性的本地游戏状态工具，维护跑团过程中的掷骰、战斗动作、物品、证物和章节进度。

## 项目内容

- `backend/`：FastAPI API、LangGraph Agent 封装、本地游戏逻辑、规则目录、存储工具和 RAG 接入代码。
- `frontend/`：React/Vite 前端应用。
- `BACKEND_API_DESIGN.md`、`FRONTEND_API_DESIGN.md`、`Walkthrough.md`：当前设计说明和交接文档。

## 未纳入仓库的本地数据

这是一个公开仓库，因此不会提交本地运行存档、D&D 原始资料或 RAG 生成产物。以下路径会被 `.gitignore` 排除：

- `backend/Game/`
- `backend/Characters/`
- `backend/Monsters/`
- `backend/Documents/`
- `backend/Knowledge/`
- `backend/data/spells.json`
- 原始提取的规则书 JSON 和测试 JSON 文件

完整本地运行时，请自行把私有数据放回对应路径。

## 后端运行

```powershell
cd backend
python -m pip install -r requirements.txt
copy .env.example .env
python main.py
```

在 `.env` 中配置 OpenAI-compatible 接口。后端会通过 LangGraph 和 LangChain 调用该接口。

## RAG 知识库构建

本地 D&D 2024 文档位于 `backend/Documents/DND5e 2024`，该目录不会提交到公开仓库。当前默认方案使用 `Qwen/Qwen3-Embedding-4B-GGUF` 的 `Qwen3-Embedding-4B-Q6_K.gguf`，并通过本地 `llama.cpp` CUDA 版 `llama-server` 提供 OpenAI-compatible `/v1/embeddings` 接口。该组合已经在 RTX 3060 Laptop 6GB 上完成验证，并已成功构建完整知识库。

```powershell
cd backend
$env:PYTHONNOUSERSITE="1"
$env:RAG_EMBEDDING_DEVICE="cuda"
python rag_ingest.py --reset
```

如需先验证切片而不加载 GGUF 模型、也不写入 Chroma，可以运行：

```powershell
cd backend
$env:PYTHONNOUSERSITE="1"
python rag_ingest.py --dry-run
```

CPU 环境只建议做小批量 smoke test：

```powershell
cd backend
$env:PYTHONNOUSERSITE="1"
python rag_ingest.py --max-chunks 2 --reset --db-path Knowledge/vector_db_smoke --collection rag_smoke
```

索引会写入 `backend/Knowledge/vector_db`，默认 collection 名称为 `dnd_rules_qwen3_embedding_4b_q6_k`。首次正式构建会把 GGUF 模型缓存到 `backend/Knowledge/hf_cache`，并使用 `backend/Knowledge/llama_cpp/` 下的本地二进制运行嵌入服务。运行时只使用该 GGUF + Chroma collection；索引不存在时 RAG 会明确显示未就绪，不会切换到旧的词法检索路径。LangGraph 当前会在规则敏感回合先判断是否需要自动检索，再规划多条 query 合并召回，并把规则片段注入本回合提示词；召回结果还会按规则关键词、标题和来源路径做一层轻量本地重排。

当前默认切片为 512 字符、80 字符 overlap，本地全量 dry-run 统计为 2948 个源文件、19694 个 chunk，当前默认知识库也已经在本机构建完成。为保证中文规则文本的稳定嵌入，`RAG_LLAMA_SERVER_CTX` 建议保持 `4096`；无 CUDA 时，脚本会阻止大批量 CPU 构建。确实要强制执行可加 `--allow-slow-cpu`，但预计会非常慢。中断后的构建可以去掉 `--reset` 直接续跑，脚本会跳过 collection 中已有的 chunk id，也支持通过 `--start-chunk` 从指定偏移继续。

LangGraph 当前会先做规则意图分类，再决定是否自动检索；命中时会把 `rag_intent` 和规划出的 query 一起注入回合上下文。工具执行后的 `validate_state` 还会同步 party combatant 镜像，并在敌方全部失去行动能力时自动结束遭遇。

## 前端运行

```powershell
cd frontend
npm install
npm run dev
```

Vite 开发服务器会把 `/api` 代理到 `http://127.0.0.1:23333`。
如果存在 `frontend/.env.development.local` 里的 `VITE_BACKEND_URL`，前端会优先直连该后端地址；`start.ps1` 会自动写入这个运行时配置，Windows 下也可以直接双击 `start.cmd` 启动。

## 当前状态

项目当前已经具备最小可运行闭环：

- 创建角色模板
- 创建怪物模板
- 创建游戏并选择初始剧本
- 与 DM Agent 对话推进剧情
- 通过本地动作接口执行攻击、施法、技能检定、豁免检定、使用物品和推进回合
- 将战斗结果、时间线和重要剧情进展写回本地 `GameState`

RAG 相关代码已经接入 LangGraph；规则原文、模型缓存和向量库不会随公开仓库发布。

## 最近工作流更新

- `backend/dm_graph.py` 现在会先规范化 `campaign.phase` 和 `scene`，再决定当前回合开放哪些工具。
- 当前已显式区分 `party_creation`、`adventure_selection`、`exploration`、`combat`、`downtime`、`level_up` 等 phase，并把 phase 目标/约束注入 DM prompt。
- `validate_state` 会在工具执行后再次校正 phase 与 scene，减少状态漂移。
- 新增 `tests/test_dm_graph_workflow.py`，用于回归这些工作流约束。

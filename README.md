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

本地 D&D 2024 文档位于 `backend/Documents/DND5e 2024`，该目录不会提交到公开仓库。Qwen3-Embedding-8B 是 8B 模型，完整构建建议在 CUDA 环境中执行：

```powershell
cd backend
$env:PYTHONNOUSERSITE="1"
$env:RAG_EMBEDDING_DEVICE="cuda"
python rag_ingest.py --reset
```

如需先验证切片而不下载或加载 8B 模型，可以运行：

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

索引会写入 `backend/Knowledge/vector_db`，collection 名称为 `dnd_rules_qwen3_embedding_8b`。首次正式构建会从 Hugging Face 下载 `Qwen/Qwen3-Embedding-8B`，模型缓存位于 `backend/Knowledge/hf_cache`。运行时只使用该 Qwen3 + Chroma collection；索引不存在时 RAG 会明确显示未就绪，不会切换到旧的词法检索路径。

当前默认切片为 512 字符、80 字符 overlap，本地全量 dry-run 统计为 2948 个源文件、19694 个 chunk。无 CUDA 时，脚本会阻止大批量 CPU 构建；确实要强制执行可加 `--allow-slow-cpu`，但预计会非常慢。中断后的构建可以去掉 `--reset` 直接续跑，脚本会跳过 collection 中已有的 chunk id。

## 前端运行

```powershell
cd frontend
npm install
npm run dev
```

Vite 开发服务器会把 `/api` 代理到 `http://127.0.0.1:23333`。

## 当前状态

项目当前已经具备最小可运行闭环：

- 创建角色模板
- 创建怪物模板
- 创建游戏并选择初始剧本
- 与 DM Agent 对话推进剧情
- 通过本地动作接口执行攻击、施法、技能检定、豁免检定、使用物品和推进回合
- 将战斗结果、时间线和重要剧情进展写回本地 `GameState`

RAG 相关代码已经接入 LangGraph；规则原文、模型缓存和向量库不会随公开仓库发布。

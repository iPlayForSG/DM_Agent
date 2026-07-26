# DM_Agent

DM_Agent 是一个本地优先的 D&D 2024 单人跑团 DM Agent 原型。项目由 FastAPI 后端、React/Vite 前端、LangGraph 多 Agent 编排层和一组确定性的本地规则工具组成，用于维护角色、遭遇、掷骰、物品、证物、时间线和章节进度。

## 功能概览

- 规则目录驱动的角色创建流程。
- 标准怪物模板读取、游戏内自定义怪物与遭遇实例化。
- 本地游戏存档与战役阶段状态。
- Director、Rules、阶段 Specialist、Auditor、Narrator 与 Suggestion Agent 协作完成对话、工具调用和剧情推进。
- 攻击、施法、技能检定、豁免检定、物品和特性使用等本地动作接口。
- 基于本地文档、Chroma 和 GGUF embedding 模型的规则 RAG。
- LangGraph checkpoint、回合暂停恢复、SSE 回合流和轻量 turn trace。

## 目录结构

- `backend/`：FastAPI API、LangGraph Agent、规则逻辑、存储、RAG 与测试。
- `frontend/`：React/Vite 前端应用。

## 本地数据

仓库不提交私有运行数据、D&D 原始资料、模型缓存或向量库产物。完整本地运行时，需要自行准备或由应用生成对应目录：

- `backend/Game/`
- `backend/Characters/`
- `backend/Documents/`
- `backend/Knowledge/`
- `backend/data/spells.json`

这些路径已由 `.gitignore` 排除。

`backend/Monsters/` 保存供 Agent 读取和实例化的标准中文怪物模板，属于仓库资产。游戏过程中由 Agent 创建的自定义怪物则保存在对应游戏存档中，不会写回标准模板目录。

## 启动项目

Windows 下可以直接双击仓库根目录的 `start.cmd`。脚本会启动后端与前端，写入前端开发态后端地址，并自动打开浏览器。

也可以手动启动：

```powershell
cd backend
python -m pip install -r requirements.txt
copy .env.example .env
python main.py
```

```powershell
cd frontend
npm install
npm run dev
```

后端通过本地 `.env` 配置 OpenAI-compatible 模型接口。真实密钥只应放在本地环境文件中，不要提交到仓库。

## RAG 知识库

RAG 使用 `backend/Documents/DND5e 2024` 下的本地规则文档构建 Chroma 向量库，默认 embedding 模型为 `Qwen/Qwen3-Embedding-4B-GGUF` 的 `Qwen3-Embedding-4B-Q6_K.gguf`。生成结果写入 `backend/Knowledge/vector_db`，不会进入 Git。

正式构建：

```powershell
cd backend
$env:PYTHONNOUSERSITE="1"
$env:RAG_EMBEDDING_DEVICE="cuda"
python rag_ingest.py --reset
```

只验证切片：

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

索引不存在或不可用时，后端会明确报告 RAG 未就绪，不会隐式切换到旧检索路径。

## 常用验证

```powershell
python -m compileall backend
```

```powershell
cd frontend
npm run build
```

激活已安装后端依赖的 Python 环境后，可在仓库根目录运行：

```powershell
python -m unittest discover -s tests -v
```

前端验证：

```powershell
cd frontend
npm run build
npm run lint
```

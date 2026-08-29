# DM_Agent

DM_Agent 是一个本地优先的 D&D 2024 单人跑团 DM Agent 原型。项目由 FastAPI 后端、React/Vite 前端、LangGraph DM Loop 和一组确定性的本地规则工具组成，用于维护角色、遭遇、掷骰、物品、证物、时间线和章节进度。

## 功能概览

- 规则目录驱动的角色创建流程；DM 可直接读取目录、落地并校验角色卡、锁定冒险。
- 标准怪物模板读取、游戏内自定义怪物与遭遇实例化。
- 遭遇 XP 预算难度分级与自定义怪物 CR 估算（算法移植自 5e.tools 开源工具集）。
- 本地游戏存档与战役阶段状态。
- 一个持续身份的 DM Brain 负责判断、工具调用和叙事；阶段只收窄上下文与能力，Suggestion Agent 在提交后独立投影行动建议。
- 攻击、施法、技能检定、豁免检定、物品和特性使用等本地动作接口。
- 基于本地文档、Chroma/GGUF embedding 与确定性词法降级的规则 RAG。
- 支持 OpenAI-compatible API、Claude Code CLI 与 Codex CLI 三种模型接入方式。
- LangGraph checkpoint、回合暂停恢复、SSE 回合流和轻量 turn trace。

## 目录结构

- `backend/`：FastAPI API、LangGraph Agent、规则逻辑、存储、RAG 与测试。
- `frontend/`：React/Vite 前端应用。

## 第三方来源

`backend/encounter_math.py` 的 XP 预算表、CR 统计表与 CR 折中算法移植自 [5e.tools](https://5e.tools) 开源工具集，只复制数值表和推导逻辑，不包含其 UI、渲染栈或正文内容；出处逐项记录在该模块头部。

`backend/utils/import_5etools_builder_options.py` 可从本地 5e.tools 数据目录增量补齐建卡目录中的物种、背景与起源专长。脚本是幂等的，只追加缺失条目，不改写已有条目：

```powershell
cd backend
python utils/import_5etools_builder_options.py --source "E:/5e Tools/data" --dry-run
python utils/import_5etools_builder_options.py --source "E:/5e Tools/data"
```

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

Windows 下可以直接双击仓库根目录的 `start.cmd`。macOS/Linux 使用 `./start.sh`。两个脚本都会启动后端与前端、写入前端开发态后端地址并打开浏览器。POSIX 脚本优先使用仓库 `.venv`，也可以通过 `DM_AGENT_PYTHON` 指定 Python 3.10+ 解释器。

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

模型设置页可以保存 OpenAI-compatible API、Claude Code CLI 或 Codex CLI 档案。API 密钥只应放在本地环境文件中，不要提交到仓库；CLI 模式复用本机 CLI 登录态，不保存额外凭据。CLI 作为受限模型传输层运行，不能绕过 LangGraph 的工具所有权和确定性状态结算。

## RAG 知识库

RAG 使用 `backend/Documents/DND5e 2024` 下的本地规则文档构建 Chroma 向量库，默认 embedding 模型为 `Qwen/Qwen3-Embedding-4B-GGUF` 的 `Qwen3-Embedding-4B-Q6_K.gguf`。生成结果写入 `backend/Knowledge/vector_db`，不会进入 Git。

先生成适合词法检索的规范化副本：

```sh
python backend/utils/normalize_rule_documents.py
```

格式要求与人工整理边界见 [`docs/RULE_DOCUMENT_STANDARD.md`](docs/RULE_DOCUMENT_STANDARD.md)。向量库、embedding 模型或 llama.cpp 服务缺失时，后端自动降级到该规范化语料的 heading-aware 词法检索；规范化副本也不存在时才直接读取原始 Markdown/text。

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

状态接口会分别报告 vector 与 lexical 是否就绪，并公开降级原因。

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

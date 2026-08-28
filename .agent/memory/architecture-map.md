# 架构地图

## 高层数据流

```text
React/Vite UI
  -> FastAPI REST/SSE
  -> DMGraphRunner LangGraph 父图
  -> Director + Rules + 当前阶段 Specialist
  -> StructuredTool / ToolNode
  -> AgentToolService + GameLogic + RuleCatalog
  -> Validator / repair / Auditor / Narrator
  -> audit_failed 时恢复 initial_game_state
  -> finalize_turn 原子提交
  -> JSON GameState + SQLite checkpoint
  -> 独立 SuggestionAgent 投影
```

前端的本地动作 API 可绕过 LLM，但仍通过 `GameActionService` 复用 `GameLogic` 和 `RuleCatalog` 的确定性规则。

## 组件职责与边界

- API 层 `backend/main.py`：请求模型、HTTP 状态码、SSE 事件、存档读写时机。
- 编排层 `backend/dm_graph.py`：阶段、Agent 路由、工具预算、校验/修复、叙事与事务边界。
- Agent 层 `backend/agents/`：角色所有权和私有子图状态；适配器才把工具结果投影回父图。
- 规则执行层：`agent_tools.py` / `action_service.py` 组织操作，`game_logic.py` 结算，`rules_catalog.py` 提供角色卡和目录事实，`encounter_math.py` 提供无状态的遭遇预算与 CR 估算。
- 数据层 `models.py`：API、存档和图状态共享的 Pydantic schema。
- 持久化层 `storage.py`：每游戏/角色/怪物一个 JSON；rewind 保存完整 `GameState`。
- 剧情记忆层 `campaign_memory.py`：只从权威 `GameState` 派生有限提示上下文，不拥有独立业务状态。
- 模型传输层 `model_backends.py`：把 OpenAI-compatible API 或受限 Claude Code/Codex CLI 适配为 LangChain chat model；CLI 不拥有游戏工具或状态。
- 检索层 `rag.py`：优先 Chroma，embedding/查询失败时降级到 `lexical_rag.py` 的确定性词法索引；`rag_embeddings.py` 按需启动本地 llama.cpp，`rag_ingest.py` 构建向量索引。
- UI 层：`App.jsx` 消费服务端快照，`api.js` 管理请求和 SSE 解析。

## 外部依赖

- OpenAI-compatible Chat Completions 端点，或本机已安装登录的 Claude Code/Codex CLI。
- LangGraph / LangChain：工作流、Agent、ToolNode、interrupt 和 checkpoint。
- FastAPI / Uvicorn / Pydantic：HTTP 与数据契约。
- React 19 / Vite 5：前端。
- ChromaDB、Qwen3-Embedding-4B GGUF、llama.cpp：可选本地规则检索。

## 持久化位置

- `backend/Game/*.json`：游戏状态；`backend/Game/_rewind/`：消息分支快照。
- `backend/Characters/*.json`：可复用角色模板。
- `backend/Monsters/*.json`：跟踪的标准怪物资产。
- `backend/runtime/checkpoints.sqlite3` 或配置路径：LangGraph checkpoint。
- `backend/Knowledge/vector_db/`：生成的 Chroma 索引。
- `backend/Knowledge/grep_corpus/`：由原始规则书生成的规范化词法语料与 manifest。
- 模型档案保存在 `backend/.env`，不得进入文档或日志。

## 关键架构约束

- `finalize_turn` 是主状态唯一提交点；失败路径从 `initial_game_state` 恢复。
- Auditor 只有明确接受才进入 Narrator；两次拒绝进入 `audit_failed`，不以重试次数作为放行条件。
- phase allowlist 与 Agent ownership 取交集决定实际工具面。
- Specialist 使用私有 state；多个写工具串行执行。
- deterministic validator 不能直接 patch 业务事实，只能要求工具修复或失败。
- checkpoint 用于 interrupt 恢复，不提供剧情分支；剧情分支由 rewind snapshot 实现。
- SSE 当前在回合完成后从 trace 派生事件，不是真实 token/tool 实时流。
- CLI 仅传输消息和应用工具调用：独立临时目录、Claude 禁用自身工具、Codex ephemeral/read-only；确定性工具仍是状态变化唯一入口。
- 向量与词法检索共享规则来源但能力不同；fallback 必须公开 vector error，不得把降级伪装成向量成功。

详细父图和角色契约见 [MULTI_AGENT_ARCHITECTURE.md](../../MULTI_AGENT_ARCHITECTURE.md)。

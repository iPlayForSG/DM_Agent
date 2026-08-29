# 架构地图

## 高层数据流

```text
React/Vite UI
  -> FastAPI REST/SSE
  -> DMGraphRunner LangGraph 父图
  -> plan / phase capability / rules context / campaign memory
  -> 持续身份的 DM Brain
  -> StructuredTool / ToolNode
  -> AgentToolService + GameLogic + RuleCatalog
  -> deterministic validate / constrained repair
  -> failed 时恢复 initial_game_state
  -> finalize_turn 原子提交
  -> JSON GameState + SQLite checkpoint
  -> 独立 SuggestionAgent 投影
```

前端的本地动作 API 可绕过 LLM，但仍通过 `GameActionService` 复用 `GameLogic` 和 `RuleCatalog` 的确定性规则。

## 组件职责与边界

- API 层 `backend/main.py`：请求模型、HTTP 状态码、SSE 事件、存档读写时机。
- 编排层 `backend/dm_graph.py`：阶段能力、上下文、工具预算、校验/修复、叙事与事务边界。
- Agent 层 `backend/agents/`：持续 DM 私有循环与提交后建议投影；适配器才把工具结果投影回父图。
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
- 普通回合没有 Director、LLM Auditor 或独立 Narrator；DM 直接生成最终叙事。
- phase allowlist 与 DM runtime ownership 取交集决定实际工具面。
- DM 使用私有 state；多个写工具串行执行。
- 状态摘要、近期历史、长期记忆和检索内容各自受独立提示词预算约束，近期历史截断时保留最新内容，避免长战役上下文挤占当前回合契约。
- 玩家输入不是世界事实源；DM 必须在先前权威状态、自己的已确认叙事或成功工具结算支持后，主动用 `record_evidence` 等工具持久化关键线索。前端状态页只投影已持久化的结构化证据。
- deterministic validator 不能直接 patch 业务事实，只能要求工具修复或失败。
- `risk_level` 只服务内部 guardrail、trace 与事务恢复，不等于玩家授权策略；明确指令和确定性结算直接执行，只有真实且尚未明确的玩家决定才使用语义化 `request_player_choice`。
- interrupt 只发布上次已提交快照和 pending 元数据，staged transaction 留在 checkpoint 中。
- 玩家选择 interrupt 只公开自然语言问题和具体选项，不公开工具名、风险等级或持久化实现；取消、失败和 checkpoint 丢失均回滚整笔 staged transaction。
- checkpoint 用于 interrupt 恢复，不提供剧情分支；剧情分支由 rewind snapshot 实现。
- SSE 当前在回合完成后从 trace 派生事件，不是真实 token/tool 实时流。
- CLI 仅传输消息和应用工具调用：独立临时目录、Claude 禁用自身工具、Codex ephemeral/read-only；确定性工具仍是状态变化唯一入口。
- 向量与词法检索共享规则来源但能力不同；fallback 必须公开 vector error，不得把降级伪装成向量成功。

详细父图和角色契约见 [MULTI_AGENT_ARCHITECTURE.md](../../MULTI_AGENT_ARCHITECTURE.md)。

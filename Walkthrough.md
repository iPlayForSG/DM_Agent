# DM_Agent Walkthrough

这份文档用于接手项目时快速建立上下文。它不是进展日志；历史实现细节应保留在 git history、测试和 API 文档中。

## 1. 项目定位

DM_Agent 是一个本地优先的 D&D 5e 2024 单人跑团主持台。

核心目标：

- 用前端提供角色、怪物、遭遇、聊天和状态管理界面。
- 用 FastAPI 保存本地游戏真相，而不是依赖模型上下文记忆。
- 用 LangGraph 编排 DM Agent，让模型负责叙事、判断意图和调用受控工具。
- 用本地规则目录与 RAG 支持规则问答和裁定。
- 让战斗、掷骰、生命值、物品、证据、日志等状态变更走结构化工具。

当前形态是可运行原型，已经具备角色模板、游戏存档、冒险选择、聊天回合、遭遇工具、动作工具、RAG、LangGraph checkpoint、暂停恢复、工具确认和 SSE trace。

## 2. 技术栈

后端：

- Python
- FastAPI
- Pydantic
- LangGraph
- LangChain / OpenAI-compatible chat model
- Chroma + Qwen3 GGUF embedding server
- 本地 JSON 文件存储
- SQLite LangGraph checkpoint

前端：

- React 19
- Vite
- `react-markdown`
- 单页应用，主要逻辑仍集中在 `frontend/src/App.jsx`

本地数据：

- `backend/Game`
- `backend/Characters`
- `backend/Monsters`
- `backend/Knowledge/vector_db`
- `backend/runtime-logs`

密钥和模型配置只放在 `backend/.env`，不要提交。

## 3. 运行与验证

一键启动：

```powershell
cmd.exe /c start.cmd
```

脚本会启动后端、启动前端，并打开浏览器。脚本内已优先使用项目 conda 环境：

```text
C:\Users\iPlayForSG\.conda\envs\DM_Agent\python.exe
```

脚本冒烟模式：

```powershell
cmd.exe /c start.cmd -ExitOnReady
```

常用检查：

```powershell
& 'C:\Users\iPlayForSG\.conda\envs\DM_Agent\python.exe' -m unittest discover -s tests
```

```powershell
npm.cmd run build
```

```powershell
git diff --check
```

后端健康检查：

```text
GET /api/v1/health
```

前端默认地址通常是：

```text
http://127.0.0.1:5173
```

后端默认从 `23333` 附近寻找可用端口；运行时端口写入：

```text
backend/runtime-logs/runtime-state.json
```

## 4. 代码结构

后端核心：

- `backend/main.py`
  - FastAPI 入口。
  - 暴露角色、怪物、游戏、遭遇、动作、RAG、trace 和 stream API。
- `backend/agent.py`
  - Agent facade。
  - 对外提供创建游戏、运行回合、恢复回合等能力。
- `backend/dm_graph.py`
  - LangGraph 主编排。
  - 负责输入检查、意图规划、阶段路由、RAG、模型调用、工具循环、状态校验、最终写回。
- `backend/agent_tools.py`
  - 框架无关的工具服务。
  - 处理掷骰、HP、状态、物品、证据、搜索、场景、遭遇、施法、怪物模板等结构化变更。
- `backend/tool_registry.py`
  - 工具契约与 guardrails。
  - 记录参数约束、风险等级、是否需要 active encounter、是否需要确认等。
- `backend/game_logic.py`
  - 游戏状态操作的底层逻辑。
- `backend/action_service.py`
  - 前端按钮动作使用的确定性动作服务。
- `backend/models.py`
  - 主要 Pydantic 模型。

规则与资料：

- `backend/rules_catalog.py`
- `backend/library.py`
- `backend/rag.py`
- `backend/rag_embeddings.py`
- `backend/rag_ingest.py`
- `backend/D&D 2024.json`
- `backend/Documents`
- `backend/Knowledge`

前端：

- `frontend/src/App.jsx`
  - 当前主要界面文件。
  - 包含主页、角色构筑、怪物模板、聊天、遭遇面板、状态页和动作面板。
- `frontend/src/api.js`
  - 后端 API client。
  - 包含普通请求和 `/turns/stream` SSE 解析。
- `frontend/src/index.css`
  - 全局样式。

文档：

- `README.md`
- `BACKEND_API_DESIGN.md`
- `FRONTEND_API_DESIGN.md`
- `LOCAL_FRAMEWORK_DECISION.md`
- `Walkthrough.md`

## 5. Agent 编排

当前 LangGraph 回合主路径：

1. `prepare_turn`
2. `input_gate`
3. `plan_turn`
4. `route_phase`
5. `retrieve_rules`
6. `prepare_context`
7. `draft_response`
8. `execute_tools`
9. `validate_state`
10. `finalize_turn`

关键原则：

- 模型不能直接改本地真相，只能通过受控工具间接变更。
- `GameState` 是事实来源。
- 工具调用必须经过 registry 和 guardrails。
- 活动遭遇中，攻击、技能检定、施法等 actor-bound 工具只能由当前行动者发起。
- 高风险工具会进入 `tool_confirmation` 暂停态，前端用确认卡片 resume。
- 回合暂停使用 LangGraph interrupt/checkpoint 和 `GameState.pending_turn`。
- 每回合写入 `TurnTrace`，用于调试、回放和前端过程展示。
- 状态校验会同时写入兼容性的 `validation_notes` 和结构化的 `validation_issues`。

当前已支持的 trace/SSE：

- `turn.started`
- `turn.node`
- `rag.completed`
- `tool.completed`
- `validation.note`
- `turn.completed`
- `turn.input_required`
- `turn.saved`
- `turn.finished`
- `turn.error`

注意：这些过程事件目前主要来自回合完成后的 `TurnTrace` 派生，不是 token 级或 tool-call 级实时 delta。

## 6. 当前能力

已具备：

- 保存和读取角色模板。
- 通过规则目录构筑 1 级角色。
- 保存和复用怪物模板。
- 创建游戏并选择初始冒险。
- 与 DM Agent 对话推进探索。
- RAG 自动注入规则上下文。
- 本地掷骰和常用动作结算。
- 开始、维护和结束遭遇。
- 管理战斗单位、先攻、当前行动者、HP、状态、物品、施法和技能检定。
- 记录聊天、时间线、工具结果、RAG metadata、状态修正和 turn trace。
- 通过 SSE 向前端展示回合过程。
- 高风险工具执行前确认。

仍是原型的部分：

- `frontend/src/App.jsx` 过大，后续需要拆组件。
- Rules Guard 已有结构化 issue 输出和当前行动者工具约束，但动作经济、法术位、专注、反应、物品消耗等严格校验仍需继续补。
- SSE 还不是真正实时 tool delta。
- 还没有 token streaming。
- 长期记忆和章节记忆编译器尚未成型。
- 浏览器级自动化测试不足。

## 7. API 入口

常用 API：

- `GET /api/v1/health`
- `GET /api/v1/config`
- `GET /api/v1/rag/status`
- `POST /api/v1/rag/search`
- `GET /api/v1/characters`
- `POST /api/v1/characters`
- `GET /api/v1/monsters`
- `POST /api/v1/monsters`
- `GET /api/v1/games`
- `POST /api/v1/games`
- `GET /api/v1/games/{game_id}`
- `POST /api/v1/games/{game_id}/select-adventure`
- `POST /api/v1/games/{game_id}/turns`
- `POST /api/v1/games/{game_id}/turns/stream`
- `GET /api/v1/games/{game_id}/traces`
- `GET /api/v1/games/{game_id}/action-options`

遭遇和动作 API 见 `BACKEND_API_DESIGN.md`。前端调用封装见 `frontend/src/api.js`。

## 8. 接手时优先看什么

建议顺序：

1. `README.md`
2. `start.cmd`
3. `backend/main.py`
4. `backend/dm_graph.py`
5. `backend/tool_registry.py`
6. `backend/models.py`
7. `frontend/src/api.js`
8. `frontend/src/App.jsx`
9. `tests/test_dm_graph_workflow.py`
10. `tests/test_main_streaming.py`

如果要改 Agent 行为，先看 `backend/dm_graph.py` 和 `backend/tool_registry.py`。

如果要改前端交互，先看 `frontend/src/App.jsx` 和 `frontend/src/api.js`。

如果要改状态结构，先看 `backend/models.py`，再同步 API 文档和测试。

## 9. 下一步队列

优先级较高：

1. 拆分 `frontend/src/App.jsx`。
   - 先抽 chat/session sidepanel/action panel。
   - 不要在同一轮重写视觉体系。
2. 强化 Rules Guard。
   - 动作经济。
   - 法术位和专注。
   - 物品数量。
   - 遭遇结束条件。
3. 细化 stream 事件。
   - 增加真正执行过程中的 `tool.started/tool.completed`。
   - 保持现有派生事件兼容。
4. 增加浏览器级 smoke。
   - 启动应用。
   - 新建游戏。
   - 选择冒险。
   - 发送回合。
   - 触发并确认 `tool_confirmation`。
5. 设计章节记忆编译器。
   - NPC 事实。
   - 任务线索。
   - 玩家偏好。
   - 证据关联。
   - 重大经历。

暂不优先：

- 重写成多 Agent 框架。
- 接 A2A。
- 把 MCP 作为核心运行依赖。
- 做开放式无限自我改写。

## 10. 工作约定

- 不要把模型输出当作事实来源；事实必须写入 `GameState`。
- 不要绕过 `AgentToolService` 直接改战斗或角色状态。
- 新增工具时同步更新 `tool_registry.py`、测试和 API 文档。
- 新增 Rules Guard 修复时同步写入 `validation_issues`，不要只追加文本 note。
- 改 `/turns/stream` 时同步更新 `tests/test_main_streaming.py`。
- 改角色、怪物、游戏模型时优先考虑旧 JSON 存档兼容。
- 保持文档短而当前；历史过程交给 git。

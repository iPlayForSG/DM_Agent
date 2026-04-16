# 后端 API 设计与 LangGraph 重构计划

## 1. 当前定位

后端是 DM Agent 的权威状态层和规则执行层。大模型负责叙事、判断意图和提出工具调用，但游戏事实必须落在本地结构化状态里。

当前后端已经具备：

1. FastAPI 顶层 HTTP API。
2. 本地 JSON 存档。
3. 角色创建规则目录。
4. 初始冒险生成与选择流程。
5. 怪物模板保存与遭遇实例化。
6. 最小遭遇与战斗状态。
7. 本地确定性动作接口。
8. RAG / 本地规则检索入口。
9. Google ADK + LiteLLM 驱动的 DM 对话链路。

接下来后端重构的核心目标是：**把当前 ADK 单回合 Agent 链路重构为 LangGraph 显式流程图**，使 DM 回合的阶段、工具、状态更新和校验都更可控。

## 2. 设计原则

1. `GameState` 是唯一权威游戏状态。
2. HTTP API 尽量保持兼容，优先重构内部实现。
3. 本地规则逻辑优先于模型自由判断。
4. 工具调用必须被阶段和状态约束。
5. RAG 只作为规则片段检索，不把大段资料长期塞进系统提示词。
6. 前端不应该感知 ADK 或 LangGraph 的内部差异。
7. 后续所有 Agent 写入都应能形成 `tool_results`、`state_delta` 和 `timeline_append`。

## 3. 核心数据模型

### 3.1 GameState

`GameState` 是游戏存档主体，当前关键字段包括：

- `characters`
- `active_character_id`
- `scene`
- `turn_number`
- `adventure_log`
- `evidence_records`
- `search_records`
- `chat_history`
- `timeline`
- `latest_tool_results`
- `encounter`
- `campaign`

重构后仍保持 `GameState` 为 API 和存档的主体模型。LangGraph 内部可以使用字典或 TypedDict 承载图状态，但进入和离开图时必须严格转换为 `GameState`。

### 3.2 CampaignFlowState

当前流程阶段包括：

- `character_creation`
- `party_creation`
- `adventure_selection`
- `exploration`
- `combat`
- `level_up`

LangGraph 重构后，`campaign.phase` 与 `scene` 将成为图路由的重要输入。

### 3.3 EncounterState

当前遭遇状态包括：

- `active`
- `round_number`
- `current_combatant_id`
- `turn_order_started`
- `initiative_order`
- `combatants`

战斗阶段的图节点必须继续遵守当前行动者约束，不能允许模型绕过本地回合规则。

### 3.4 TurnResult

`POST /api/v1/games/{game_id}/turns` 当前返回：

- `response`
- `history`
- `history_append`
- `timeline`
- `timeline_append`
- `tool_results`
- `state_delta`
- `game_state`

LangGraph 重构后该响应结构保持兼容。

## 4. 当前 HTTP API

### 4.1 基础接口

- `GET /api/v1/health`
- `GET /api/v1/config`

`GET /api/v1/config` 当前返回 `chat_backend: "google-adk"`。完成 LangGraph 替换后应改为：

```json
{
  "chat_backend": "langgraph",
  "model_provider": "openai-compatible"
}
```

### 4.2 规则目录

- `GET /api/v1/rules/character-builder`

该接口返回角色创建器所需规则目录，包括物种、背景、起源专长、职业、起始资源、起始装备、起始法术和职业法术位。

### 4.3 RAG / 知识检索

- `POST /api/v1/rag/search`

该接口主要用于手动验证知识库是否可检索。Agent 侧继续通过工具调用进入同一套底层检索逻辑。

当前 RAG 链路约定：

1. 优先使用持久化 Chroma 向量库。
2. 如果 `chromadb` 不可用，则回退到基于 `rg` 的本地 markdown 检索。
3. Agent 通过规则检索工具显式拉取片段，不把大段检索文本永久写入系统提示词。

### 4.4 资料接口

- `GET /api/v1/library/classes`
- `GET /api/v1/library/spells/{class_name}`

`GET /api/v1/library/spells/{class_name}` 会经过 `RuleCatalog.resolve_spell_library_key()` 做兼容映射，避免历史编码或职业名称差异直接影响前端。

### 4.5 角色接口

- `GET /api/v1/characters`
- `POST /api/v1/characters`
- `GET /api/v1/characters/{identifier}`

角色保存时会自动补全或校验：

- `save_proficiencies`
- `spells.ability`
- `spells.casting_mode`
- `spells.slots`
- `resources`
- `inventory`
- `gold_gp`
- 基础 `ac`

### 4.6 怪物模板接口

- `GET /api/v1/monsters`
- `POST /api/v1/monsters`
- `GET /api/v1/monsters/{identifier}`

怪物模板是长期资产，可以由 DM Agent 保存，并在遭遇系统中实例化为敌方或其他阵营的 combatant。

### 4.7 游戏流程接口

- `GET /api/v1/games`
- `POST /api/v1/games`
- `GET /api/v1/games/{game_id}`
- `GET /api/v1/games/{game_id}/action-options`
- `POST /api/v1/games/{game_id}/select-adventure`
- `POST /api/v1/games/{game_id}/turns`

`POST /api/v1/games/{game_id}/turns` 是 Agent 回合入口。LangGraph 重构必须保持该接口的输入输出兼容。

### 4.8 遭遇接口

- `POST /api/v1/games/{game_id}/encounters/start`
- `POST /api/v1/games/{game_id}/encounters/add-enemy`
- `POST /api/v1/games/{game_id}/encounters/spawn-template`
- `POST /api/v1/games/{game_id}/encounters/end`
- `POST /api/v1/games/{game_id}/encounters/remove-combatant`
- `POST /api/v1/games/{game_id}/encounters/set-initiative`
- `POST /api/v1/games/{game_id}/encounters/roll-initiative`

这些接口由本地逻辑直接执行，不依赖大模型。

`encounters/end` 会通过 `GameLogic` 的统一总结入口结束遭遇，返回结构化遭遇摘要，并把文本摘要追加到 `adventure_log`。

### 4.9 本地确定性动作接口

- `POST /api/v1/games/{game_id}/actions/advance-turn`
- `POST /api/v1/games/{game_id}/actions/attack`
- `POST /api/v1/games/{game_id}/actions/skill-check`
- `POST /api/v1/games/{game_id}/actions/saving-throw`
- `POST /api/v1/games/{game_id}/actions/cast-spell`
- `POST /api/v1/games/{game_id}/actions/use-item`

这些接口在激活遭遇中会校验当前行动者，拒绝非当前回合持有者的本地动作请求。

## 5. 当前 ADK 工具能力

当前 `DMAgent` 通过 ADK tools 暴露的能力包括：

- `lookup_rules`
- `roll_dice`
- `adjust_hp`
- `add_status`
- `remove_status`
- `append_adventure_log`
- `add_inventory_item`
- `record_major_experience`
- `record_chapter_progress`
- `set_defeat_state`
- `set_scene`
- `set_active_character`
- `start_encounter`
- `add_enemy`
- `save_monster_template`
- `spawn_monster_from_template`
- `attack_target`
- `roll_skill_check`
- `roll_saving_throw`
- `cast_spell`
- `set_initiative`
- `roll_initiative`
- `advance_turn`
- `end_encounter`

重构目标不是删除这些能力，而是把它们从 ADK `ToolContext` 闭包中拆出来，变成框架无关的本地 tool/service，再由 LangGraph 节点调用。

## 6. LangGraph 重构目标

### 6.1 目标流程

```text
POST /api/v1/games/{game_id}/turns
  -> load GameState
  -> DMGraph.invoke(...)
     -> prepare_turn
     -> route_phase
     -> prepare_context
     -> retrieve_rules
     -> call_dm_model
     -> execute_tool_calls
     -> validate_state
     -> finalize_turn
  -> save GameState
  -> return TurnResult
```

### 6.2 建议图状态

```text
DMGraphState
  game_state: dict
  user_input: str
  phase: str
  scene: str
  messages: list
  state_summary: str
  recent_history: str
  rule_snippets: list
  allowed_tools: list[str]
  pending_tool_calls: list
  tool_results: list
  state_delta: dict
  timeline_append: list
  final_response: str
```

### 6.3 建议节点职责

`prepare_turn`

- 深拷贝传入的 `GameState`。
- 追加玩家事件。
- 初始化 `tool_results`、`state_delta`、`timeline_append`。

`route_phase`

- 根据 `campaign.phase`、`scene`、`encounter.active` 决定当前回合走探索、战斗、升级或冒险选择流程。

`prepare_context`

- 调用 `GameLogic.get_state_summary()`。
- 读取近期历史。
- 生成模型需要的最小上下文。

`retrieve_rules`

- 当用户输入或当前阶段需要规则支持时调用本地 RAG。
- 返回带来源的规则片段。

`call_dm_model`

- 使用 OpenAI-compatible chat model。
- 将可用工具限制在当前阶段允许范围内。

`execute_tool_calls`

- 执行模型请求的工具。
- 工具必须只通过本地 service 修改 `GameState`。
- 每次工具执行都生成 `ToolResult`。

`validate_state`

- 校验遭遇状态、当前行动者、资源消耗、法术位、物品数量和状态变更。
- 对不合法工具调用返回错误结果，而不是让模型直接修改状态。

`finalize_turn`

- 追加 DM 回复事件。
- 更新 `chat_history`。
- 写入 `latest_tool_results`。
- 返回兼容的 `TurnResult`。

## 7. 工具分层计划

### 7.1 第一层：框架无关工具服务

新增或整理一个工具执行层，例如：

- `backend/agent_tools.py`
- `backend/dm_graph.py`
- `backend/tool_registry.py`

工具函数不应该依赖 ADK `ToolContext` 或 LangGraph runtime；它们应接收显式参数：

```text
tool(state: GameState, args: ToolArgs, services: ToolServices) -> ToolExecutionResult
```

### 7.2 第二层：LangGraph 适配层

LangGraph 节点负责：

- 从图状态取出 `GameState`。
- 校验当前阶段是否允许该工具。
- 调用工具服务。
- 把结果合并回图状态。

### 7.3 第三层：HTTP 复用

公开的本地动作 API 应继续复用同一套 service，避免 HTTP 路径和 Agent 路径产生两套规则。

## 8. 阶段化迁移计划

### Phase 1: 拆出工具执行层

目标：

- 保持 ADK 仍可运行。
- 把 `agent.py` 中的工具闭包逐步拆到框架无关模块。
- 工具结果结构统一。

验收：

- ADK 旧链路仍能跑通。
- 本地动作接口不回退。
- `python -m compileall backend` 通过。

### Phase 2: 建立 LangGraph 单回合等价链路

目标：

- 新增 LangGraph runner。
- 保持 `DMAgent.run_turn()` 对外签名不变。
- 用 LangGraph 完成当前 ADK 同等能力。

验收：

- `/turns` 返回结构不变。
- `config.chat_backend` 可以切换为 `langgraph`。
- 探索对话、工具调用、时间线追加正常。

### Phase 3: 显式阶段路由

目标：

- 按 `campaign.phase` 和 `scene` 划分 graph 路径。
- 战斗阶段限制工具白名单。
- 冒险选择、探索、战斗、升级流程分离。

验收：

- 战斗中不允许越过当前行动者执行本地动作。
- 非战斗阶段不会暴露战斗推进工具。
- 遭遇结束后正确回到 `exploration`。

### Phase 4: 强化 RAG 与规则守卫

目标：

- RAG 查询成为 graph 中可观察节点。
- 按阶段和意图决定是否检索规则。
- 规则片段进入模型上下文前做长度和来源控制。

验收：

- `lookup_rules` 等价能力保留。
- RAG 不可用时仍有本地 fallback。
- 工具调用错误能回传给模型修正。

### Phase 5: 可恢复执行与观测

目标：

- 评估是否接入 LangGraph checkpointer。
- 给每个游戏回合分配 thread/run id。
- 记录节点级工具执行和状态变更。

验收：

- 失败回合可以定位到节点。
- 工具副作用具备幂等保护。
- 长流程中断恢复方案明确。

## 9. 不在本次重构第一阶段处理的内容

以下内容暂不和 LangGraph 替换绑定：

- 完整 D&D 资料 RAG 重切片。
- 远程数据库存档。
- 多用户账户系统。
- Google Cloud / Agent Engine 部署。
- 完整升级规则。
- 前端大组件拆分。

这些事项应在 Agent 编排稳定后再逐步推进。

## 10. 后续验证清单

每个后端重构阶段至少执行：

1. `python -m compileall backend`
2. 前端 `npm run build`
3. 创建角色 smoke test
4. 创建游戏 smoke test
5. 选择冒险 smoke test
6. `/turns` 普通探索回合 smoke test
7. 开始遭遇、攻击、推进回合 smoke test
8. 施法与法术位消耗 smoke test
9. 结束遭遇并写入 `adventure_log` smoke test
10. RAG 查询 smoke test

## 11. 重要约束

1. 不要让模型直接写任意 `GameState` JSON。
2. 不要把工具权限只写在 prompt 中。
3. 不要为了迁移 LangGraph 改动前端 API 契约。
4. 不要在第一阶段引入新的持久化基础设施。
5. 不要把本地 D&D 资料和测试存档纳入 Git。

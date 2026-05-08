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
9. LangGraph + LangChain 驱动的 DM 对话链路。

当前后端重构的核心目标是：**用 LangGraph 显式流程图完全替换原 ADK 单回合 Agent 链路**，使 DM 回合的阶段、工具、状态更新和校验都更可控。

## 2. 设计原则

1. `GameState` 是唯一权威游戏状态。
2. HTTP API 尽量保持兼容，优先重构内部实现。
3. 本地规则逻辑优先于模型自由判断。
4. 工具调用必须被阶段和状态约束。
5. RAG 只作为规则片段检索，不把大段资料长期塞进系统提示词。
6. 前端不应该感知 Agent 编排框架的内部细节。
7. 后续所有 Agent 写入都应能形成 `tool_results`、`state_delta` 和 `timeline_append`。

## 2.1 当前模型配置

后端统一通过 OpenAI-compatible 接口调用模型，具体模型和 base URL 可以随时切换。运行时从环境变量读取：

- `LLM_MODEL`
- `OPENAI_API_BASE` / `OPENAI_BASE_URL`
- `OPENAI_API_KEY`

真实密钥和运行时选定的模型只写入本地 `backend/.env`，该文件已被 `.gitignore` 忽略，不能提交或推送；公开仓库只保留无密钥的 `backend/.env.example`。LangGraph 通过 `ChatOpenAI(base_url=..., model=...)` 直接调用，不依赖特定厂商。

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

`GET /api/v1/config` 当前返回：

```json
{
  "chat_backend": "langgraph",
  "model_provider": "openai-compatible"
}
```

### 4.2 规则目录

- `GET /api/v1/rules/character-builder`

该接口返回角色创建器所需规则目录，包括物种、背景、起源专长、职业、起始资源、起始装备、起始法术和职业法术位。最近一轮又补了两类 builder 专用字段：

- 顶层 `equipment_shop_items`：角色创建器“自定义购买”模式的本地装备目录，包含 `id`、`cost_gp`、`bundle_size`、`type`、伤害/护甲元数据等
- 每个职业上的 `custom_purchase_budget_gp` / `custom_purchase_option_id`：用于把“金币开局”分支显式暴露给前端分步向导

返回体会经过 `_add_display_fields` 包一层：对已知 display 字段（`name`、`label`、`description`、`origin_feat`、`class_name`、`background_name`、`species`、`type`、`damage_type`、`creature_type`、`recovery` 等）生成对应的 `*_display` 兄弟字段，内部规则键保持原样。前端在角色构筑页直接消费 `*_display` 字段渲染中文，缺失时回退到 canonical 英文。`backend/library.py` 的 `TERM_TRANSLATIONS` 是这一层本地化的唯一真源，新增条目时应统一加在那里。

### 4.3 RAG / 知识检索

- `GET /api/v1/rag/status`
- `POST /api/v1/rag/search`

这些接口主要用于手动验证知识库是否可检索。Agent 侧继续通过图节点和工具调用进入同一套底层检索逻辑。

当前 RAG 链路约定：

1. 使用持久化 Chroma 向量库，默认 collection 为 `dnd_rules_qwen3_embedding_4b_q6_k`。
2. 向量由 `Qwen/Qwen3-Embedding-4B-GGUF` 的 `Qwen3-Embedding-4B-Q6_K.gguf` 生成，嵌入服务通过本地 `llama.cpp` `llama-server` 提供 OpenAI-compatible `/v1/embeddings` 接口。
3. 文档向量直接嵌入切片正文；查询向量会统一加上 `Instruct: ... / Query: ...` 前缀后再嵌入，以保持 Qwen3 retrieval 用法一致。
4. 源文档目录为 `backend/Documents/DND5e 2024`，生成的 Chroma 数据库写入 `backend/Knowledge/vector_db`。
5. 如果 `chromadb` 或目标 collection 不可用，则 RAG 状态明确标记为未就绪，不再回退到旧的词法检索。
6. LangGraph 每回合通过 `retrieve_rules` 节点先做规则意图分类，再判断当前输入是否属于规则敏感回合；命中触发条件时才自动检索，模型仍可通过 `lookup_rules` 工具做二次检索。
7. 自动检索不会只拿用户原句做一次向量召回，而是会结合当前 `scene`、`campaign.phase`、主动角色职业/法术和命中的规则关键词规划多条 query，再合并结果做轻量去重。
8. 多 query 召回后还会按规则关键词对标题、来源路径和正文做轻量本地重排，尽量把主题更贴近的规则片段排在前面。
9. Agent 不把大段检索文本永久写入系统提示词，只在当前回合上下文中使用片段。
10. 运行时会限制单次注入总长度，并对同一来源的候选结果做轻量去重；`GET /api/v1/rag/status` 当前会把后端标记为 `chroma-llama-cpp-gguf`。

### 4.4 资料接口

- `GET /api/v1/library/classes`
- `GET /api/v1/library/spells/{class_name}`

`GET /api/v1/library/spells/{class_name}` 会经过 `RuleCatalog.resolve_spell_library_key()` 做兼容映射，避免历史编码或职业名称差异直接影响前端。

### 4.5 角色接口

- `GET /api/v1/characters`
- `POST /api/v1/characters`
- `GET /api/v1/characters/{identifier}`

角色列表 (`GET /api/v1/characters`) 和怪物列表 (`GET /api/v1/monsters`) 返回的每条 summary 也会经过 `_add_display_fields` 包一层，补齐 `name_display`、`class_name_display`、`creature_type_display` 等字段供前端直接渲染中文。

角色保存时会自动补全或校验：

- `save_proficiencies`
- `spells.ability`
- `spells.casting_mode`
- `spells.slots`
- `resources`
- `inventory`
- `gold_gp`
- 基础 `ac`

`POST /api/v1/characters` 现在额外接受并消费 builder 字段：

- `equipment_mode`
- `custom_purchase_items`
- `custom_pending_item`
- `starter_option_id`
- `starter_choice_ids`

后端会基于这些字段做三类额外约束：

1. 角色创建属性改为按 `ability_generation.point_buy` 校验，限制 8-15 与 27 点预算
2. level 1 生命值改为按职业生命骰和体质修正自动推导并强校验，不再允许前端手填任意 `hp_max`
3. 起始装备支持“标准套装 / 自定义购买 / 自定义待定装备”三段式物化：自定义购买会约束预算，自定义待定装备会占用预留金币并记录为 `dm_pending`

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

`POST /api/v1/games` 当前除了创建存档，还会直接返回：

- `status`
- `game`
- `game_state`
- `action_options`

这样前端在建局成功后可以直接进入 `adventure_selection`，不需要立刻追加一次 `GET /games/{game_id}` 和 `GET /games/{game_id}/action-options`。
返回的 `game_state` 与 `action_options` 也会携带一部分本地化后的 `*_display` 字段，供前端直接渲染中文职业、法术、物品类型、伤害类型和 defeat state，同时保留内部 canonical 规则字段不变。

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

## 5. 当前 LangGraph 工具能力

当前 `DMAgent` 通过 LangGraph tool calling 暴露的能力包括：

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

这些能力已经从原 ADK `ToolContext` 闭包中拆出，变成框架无关的本地 tool/service，再由 LangGraph 节点调用。

当前进展：

- 已新增 `backend/agent_tools.py`。
- 已引入 `AgentToolService` 与 `AgentToolExecution`，用于承载框架无关工具执行结果。
- LangGraph 工具执行节点已委托到 `AgentToolService`。
- `agent.py` 已变为 LangGraph-only facade，不再保留 ADK orchestration 外壳。
- 原 ADK wrapper 与 `_build_tools()` 已删除。

## 6. LangGraph 重构目标

### 6.1 目标流程

```text
POST /api/v1/games/{game_id}/turns
  -> load GameState
  -> DMGraph.invoke(...)
     -> prepare_turn
     -> route_phase
     -> retrieve_rules
     -> prepare_context
     -> call_dm_model
     -> execute_tool_calls
     -> validate_state
     -> finalize_turn
  -> save GameState
  -> return TurnResult
```

当前进展：

- 已新增 `backend/dm_graph.py`。
- 已声明 `langgraph`、`langchain`、`langchain-openai` 后端依赖。
- `DMGraphRunner` 当前包含 `prepare_turn -> route_phase -> retrieve_rules -> prepare_context -> draft_response -> execute_tools -> validate_state -> finalize_turn` 的单回合图。
- `draft_response` 在 `enable_model=True` 时会调用 OpenAI-compatible `ChatOpenAI` 模型节点。
- 已接入 `execute_tools` 节点，能够执行模型返回的 tool calls，并把 `ToolResult`、`timeline_append` 和 `state_delta` 合并回图状态。
- 已接入 `retrieve_rules` 节点，能够在模型调用前先做规则意图分类，再按当前状态做自动 query planning，并从 Qwen3/Chroma RAG 中取回带来源片段。
- `retrieve_rules` 的结果现在会先经过轻量本地重排，再注入回合 prompt。
- 自动检索当前会区分 `rules_question`、`combat_resolution`、`spell_resolution`、`condition_resolution`、`skill_resolution` 和 `rest_recovery` 等意图。
- 已按当前场景生成 `allowed_tools`。非战斗阶段保留检定、豁免、施法、HP 与状态变化等常见规则结算工具；战斗阶段额外暴露遭遇、攻击、先攻、推进回合和结束遭遇工具。
- 已将 `route_phase` 拆成独立节点，当前负责写入 `phase`、`scene` 和 `allowed_tools`；后续可以从这里扩展条件分支。
- 已接入 `validate_state` 节点，当前会在工具执行后修复缺失的 `active_character_id`、悬空的 `current_combatant_id`，并在遭遇激活/结束时校正 `scene` 与 `campaign.phase`。
- `validate_state` 现已进一步复用 `GameLogic` 整理先攻顺序、自动启动回合序列，并在玩家回合同步 `active_character_id`。
- `validate_state` 现已开始承担更明确的 Rules Guard 职责：会同步 party combatant 镜像，并在敌方全部失去行动能力时自动结束遭遇并追加时间线事件。
- `DMAgent` 已固定使用 LangGraph runner，不再支持 ADK 后端切换。
- 默认后端已切换为 `langgraph`。
- LangGraph 模型节点直接调用模型 provider，不再吞掉 provider 异常；真实 smoke test 需要直接暴露 provider 与工具调用链路问题。
- `dm_graph.py` 使用可选导入保护，依赖缺失时会在 LangGraph runner 初始化或执行阶段显式报错。

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
  rag_snippets: list
  rag_context: str
  rag_queries: list[str]
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

- 先把输入归类为显式规则问答、施法裁定、战斗裁定、状态裁定、技能裁定或休息恢复，再决定是否自动检索。
- query planning 会复用 `scene`、`campaign.phase`、主动角色、匹配到的法术名和规则关键词，而不是只搜用户原句。
- 检索结果会把 `rag_intent` 和 retrieval focus 一起写回图状态，便于后续 prompt 注入和调试观察。
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

- 继续承担最小状态修复，同时开始承担更明确的 Rules Guard 职责。
- 会在校验前先同步 party combatant 与角色卡的 HP、AC、状态和 defeat state，减少镜像漂移。
- 当敌方全部失去行动能力时会自动结束遭遇，写回 encounter summary，并追加自动结束事件到 `timeline_append`。
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

工具函数不应该依赖 LangGraph runtime；它们应接收显式参数：

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

- 保持 HTTP API 契约不变。
- 把 `agent.py` 中的工具闭包逐步拆到框架无关模块。
- 工具结果结构统一。

验收：

- LangGraph 工具链路能跑通。
- 本地动作接口不回退。
- `python -m compileall backend` 通过。

当前状态：

- Phase 1A 已完成：`backend/agent_tools.py` 已承载当前 Agent 工具执行逻辑。
- LangGraph 工具节点已经通过 `AgentToolService` 调用新工具服务。
- Phase 1B 已完成：`_build_tools()` 中迁移前的旧闭包参考代码已经删除。

### Phase 2: 建立 LangGraph 单回合等价链路

目标：

- 新增 LangGraph runner。
- 保持 `DMAgent.run_turn()` 对外签名不变。
- 用 LangGraph 完成原 ADK 同等能力。

验收：

- `/turns` 返回结构不变。
- `config.chat_backend` 可以切换为 `langgraph`。
- 探索对话、工具调用、时间线追加正常。

当前状态：

- Phase 2A 已完成：LangGraph runner 骨架已落地。
- Phase 2B 已完成：依赖已声明并安装到本地 `DM_Agent` conda 环境，OpenAI-compatible 模型节点和运行时切换开关已接入。
- Phase 2C 已完成：LangGraph 工具调用循环和第一版阶段化工具过滤已接入。
- Phase 2D 已完成：`route_phase` 已成为独立图节点。
- Phase 2E 已完成：非战斗阶段工具白名单已补齐常见规则结算能力。
- Phase 2F 已完成：LangGraph 普通探索回合和要求模型调用 `roll_dice` 的工具回合 smoke test 均已在 OpenAI-compatible 后端上通过；模型节点恢复为直接 `model.invoke(...)`，不做 provider 异常兜底。运行时具体使用的模型由 `.env` 中的 `LLM_MODEL` 决定，可以随时切换。
- Phase 2G 已完成：`agent.py` 已删除 ADK orchestration，后端依赖已移除 `google-adk` 与 `litellm`，`DMAgent` 固定委托到 LangGraph。
- Phase 4A 已完成：Qwen3-Embedding-4B-GGUF + llama.cpp ingestion/runtime 检索方案已接入，`retrieve_rules` 成为 LangGraph 显式节点。
- 尚未完成：更细的条件分支、更完整的节点级状态校验和后续 RAG 排序策略。

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
- RAG 不可用时明确返回未就绪状态和错误信息，不隐式切换到旧检索路径。
- 工具调用错误能回传给模型修正。

当前状态：

- Phase 4A 已完成：`backend/rag_ingest.py` 使用 `Qwen/Qwen3-Embedding-4B-GGUF` 的 `Qwen3-Embedding-4B-Q6_K.gguf` 为 `backend/Documents/DND5e 2024` 构建 Chroma collection，并通过本地 `llama.cpp` server 生成 embeddings。
- `rag_ingest.py --dry-run` 可在不加载大模型、不写入 Chroma 的情况下验证 D&D markdown 切片。
- 默认切片已调整为 512 字符、80 字符 overlap，本地全量 dry-run 已验证 2948 个源文件会生成 19694 个 chunk。
- RTX 3060 Laptop 6GB 已验证可本地加载该 GGUF 模型并输出 2560 维归一化向量；仓库默认配置改为 `RAG_LLAMA_SERVER_CTX=4096`、`RAG_EMBEDDING_BATCH_SIZE=32`，优先保证中文规则 chunk 的稳定嵌入。
- ingestion 写入 `rag_manifest.json`，记录 running/complete 状态、chunk 总数、已嵌入数和跳过数；非 `--reset` 运行会跳过已有 chunk id 以支持续跑。
- Runtime `RAGEngine` 使用同一 GGUF 模型生成 query embedding，并通过 `query_embeddings` 检索，避免 ingestion 和 query 使用不同 embedding 函数。
- Runtime `RAGEngine` 现已支持多 query 合并召回；`DMGraphRunner` 会先做规则意图分类，再结合 `scene`、`phase`、主动角色和规则关键词规划最多 4 条 query。
- Runtime `RAGEngine` 默认开启轻量本地重排，可通过 `RAG_RERANK_ENABLED` 关闭。
- `DMGraphRunner` 会把自动检索得到的 `rag_intent` 一并写入图状态，并在注入片段前显式标记 retrieval intent。
- Runtime 已移除 `rg` fallback；只有目标 Qwen3/Chroma collection 非空时 `rag_enabled` 才为 true。
- Runtime 支持 `refresh()`，`GET /api/v1/rag/status` 会刷新并返回 collection 计数、模型、路径和错误信息；当前本地默认 collection `dnd_rules_qwen3_embedding_4b_q6_k` 已构建完成，计数为 19694。
- `DMGraphRunner` 已在 `prepare_context` 前加入 `retrieve_rules` 节点，并把规则片段直接注入当前回合 prompt；普通叙事输入默认跳过自动检索，规则问答、施法裁定、战斗裁定、状态裁定和休息恢复会触发注入。工具执行后的 `validate_state` 还会把修正说明写回下一轮模型消息流。
- `validate_state` 现已在敌方全部失去行动能力时自动结束遭遇，回写 encounter summary 到 `adventure_log`，并追加自动结束的 `encounter_ended` timeline event。

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

- RAG 的自动化增量重建、召回排序和后续重排策略。
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

## 11. 2026-05-07 Workflow Update

- `route_phase` 不再只把 `campaign.phase`/`scene` 原样抄进图状态；它现在会先按 `encounter.active`、`setup_complete`、`selected_adventure_id`、`scene` 推导规范 phase，并同步修正 `scene`。
- phase policy 现已显式化：`party_creation`、`character_creation`、`adventure_selection`、`exploration`、`combat`、`downtime`、`level_up` 都有独立的工具白名单、阶段目标和约束。
- `prepare_context` 现在会把 phase 名称、目标、约束和 blockers 一并注入 DM prompt，模型不再只依赖 `state_summary` 自己猜当前流程。
- `validate_state` 在原有战斗修复之外，现会复用同一套 phase normalization，把工具执行后的场景/阶段重新拉回规范路径。
- `route_phase` 现在还会附带轻量 `turn_profile`：区分 `setup_guidance`、`conversation`、`rules_reference`、`action_resolution`、`combat_resolution`，并据此收紧工具白名单与 tool round budget，避免普通对话误入重工具链。
- 在 `turn_profile` 之上，运行时还会生成一层确定性的 `turn_advice`，给出 expected flow、suggested tools 和 checklist，用来减少模型在本回合里的工具试探成本。
- 规则检索判定已收紧：普通社交/叙事问句不会再因为单纯带问号就触发自动 RAG；只有命中明确规则/法术/状态/战斗关键词时才会自动检索。
- 新增 `tests/test_dm_graph_workflow.py`，当前覆盖：
  - 冒险未选定时自动回落到 `adventure_selection`
  - phase 指南成功注入 prompt
  - 活跃遭遇会强制恢复 `combat`
  - `level_up` 阶段不会暴露遭遇/攻击工具
  - 社交问句保持 `conversation` profile
  - 纯规则问句限制为 `lookup_rules`
  - 战斗动作保持 `combat_resolution`
## 2026-05-08 Workflow Persistence Update

- `POST /api/v1/games/{game_id}/turns` 不再只是“始终开启一个全新回合”。
  - 如果 `game_state.pending_turn` 为空，后端会按正常流程启动一个新回合。
  - 如果 `game_state.pending_turn` 已存在，后端会自动把这次输入当作对上一次暂停回合的补充说明，并直接恢复执行。
- `TurnResult` 新增两个运行时字段：
  - `turn_status`：当前取值至少包括 `completed` 和 `input_required`。
  - `pending_input`：当 `turn_status=input_required` 时返回，包含 `kind`、`phase`、`prompt` 和 `details`，供前端直接展示补充输入提示。
- `GameState` 新增 `pending_turn`：
  - 用来保存当前等待补充输入的 thread 信息和提示内容。
  - 这让前端和存档层能知道“当前不是普通对话结束，而是工作流暂停中”。
- `backend/dm_graph.py` 现已在可用时用 `InMemorySaver` 编译 LangGraph，并在 `prepare_turn` 之后插入最小 `input_gate`。
  - 空输入会直接触发 `input_required`。
  - 在 `adventure_selection` 和 `combat` 阶段，过于泛化的“继续/开始/就这样”这类输入也可能触发澄清暂停。
- 当前限制：
  - 现在的 checkpointer 仍然是进程内内存实现，只保证同一次后端进程生命周期内可恢复。
  - 如果服务重启，后端会清掉失效的 `pending_turn`，并退回普通新回合执行，而不是跨重启恢复到原 checkpoint。

## 2026-05-08 Durable Checkpoint Update

- 默认 checkpoint 后端已经从纯 `InMemorySaver` 提升为本地 SQLite。
  - 依赖：`langgraph-checkpoint-sqlite`
  - 默认路径：`backend/Game/langgraph_checkpoints.sqlite`
  - 可通过 `LANGGRAPH_CHECKPOINT_MODE` 与 `LANGGRAPH_CHECKPOINT_DB_PATH` 配置
- `LANGGRAPH_CHECKPOINT_MODE` 当前支持：
  - `sqlite`：默认值，优先使用 SQLite 持久化 checkpoint
  - `memory`：只用于测试或临时调试
  - `none`：禁用 checkpoint
- 如果本机缺少 SQLite checkpointer 依赖，或 SQLite 初始化失败：
  - 运行时会自动降级到 `memory`
  - 同时在健康检查与配置接口中暴露 `checkpoint_warning`
- `GET /api/v1/health` 和 `GET /api/v1/config` 现在都会返回：
  - `checkpoint_backend`
  - `checkpoint_db_path`
  - `checkpoint_warning`
- `/turns` 的 pause/resume 语义保持不变，但现在在同一 checkpoint 库存在时，已经支持跨 `DMGraphRunner` 实例恢复，不再局限于同一 Python 进程内存对象。
- 当前仍未完成的部分：
  - 还没有做 SSE turn lifecycle
  - 还没有做 trace logging / replay eval
  - 还没有升级到 Postgres 级别的生产持久化

## 2026-05-08 Streaming Turn Lifecycle Update

- 新增 `POST /api/v1/games/{game_id}/turns/stream`
  - `Content-Type: text/event-stream`
  - 请求体与 `POST /api/v1/games/{game_id}/turns` 相同，仍然是：
    - `{"message": "..."}`
- 当前会按顺序发送最小生命周期事件：
  - `turn.started`
  - `turn.completed` 或 `turn.input_required`
  - `turn.saved`
  - `turn.finished`
  - 失败时改为：
    - `turn.started`
    - `turn.error`
    - `turn.finished`
- 事件 payload 设计：
  - `turn.started`：`game_id`、`mode`、`checkpoint_backend`、`checkpoint_db_path`、`has_pending_turn`
  - `turn.completed` / `turn.input_required`：完整 `TurnResult` JSON，再补 `game_id` 与 `mode`
  - `turn.saved`：`game_id`、`turn_status`、`updated_at`
  - `turn.finished`：最终 `status`
- 兼容性说明：
  - 原 `POST /api/v1/games/{game_id}/turns` 保持不变，仍返回完整 `TurnResult`
  - 新的 stream 接口只是把同一回合执行过程拆成前端可消费的 SSE 生命周期事件
- 现阶段边界：
  - 还没有把工具调用中间态逐条流出
  - 还没有把 RAG 召回中间态逐条流出
  - 还没有做 server-side heartbeat / keepalive

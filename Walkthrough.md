# DM_Agent Walkthrough

## 1. 文档用途

这是一份给后续开发者或 Agent 使用的项目交接文档。

目标：

1. 说明项目最终要实现什么。
2. 说明当前代码已经做到哪里。
3. 说明下一步最应该做什么。
4. 说明仓库里关键文件分别负责什么。
5. 说明如何在本地继续运行、验证和扩展。

当前下一阶段重点：**继续强化 LangGraph 后端 Agent 编排**。

最新进展：已经完成 Phase 1A、Phase 1B、Phase 2A、Phase 2B、Phase 2C、Phase 2D、Phase 2E、Phase 2F 和 Phase 2G。`backend/agent_tools.py` 已承载框架无关工具层；`backend/agent.py` 已变为 LangGraph-only facade；`backend/dm_graph.py` 已加入 LangGraph runner、OpenAI-compatible 模型节点、工具调用循环、独立 `route_phase` 节点和第一版阶段化工具白名单；Z.AI GLM-5.1 下的普通回合与 `roll_dice` 工具回合 smoke test 已通过。

当前本地模型配置已切换为 Z.AI GLM-5.1：`LLM_MODEL=glm-5.1`，base URL 使用 `https://open.bigmodel.cn/api/coding/paas/v4`。真实 API key 只在 `backend/.env` 中保存，该文件被 `.gitignore` 忽略，不能提交或推送。

## 2. 项目最终目标

DM_Agent 是一个以 D&D 5e 2024 为规则基准的单人跑团 Agent。

理想形态应覆盖完整流程：

1. DM 引导用户创建角色。
2. 用户按规则创建 1 到 4 人初始小队。
3. DM 生成若干初始冒险摘要，用户选择其一。
4. 正式进入冒险流程，用户与 DM 对话推进剧情。
5. 本地持续维护并保存小队角色数据：
   - 生命值与临时生命值
   - 经验值或里程碑状态
   - 法术位
   - 已知 / 已准备法术
   - 装备、消耗品、金币
   - 灵感
   - 状态效果
   - 职业资源
   - 重大经历摘要
6. 进入战斗时自动切到战斗状态：
   - 显示参战者状态
   - 显示回合与先攻
   - 显示敌我单位
   - 控制法术位、资源、消耗品的合法使用
7. 所有骰子和规则结算通过本地逻辑生成。
8. 升级时给出升级模板或升级流程，并按 2024 规则更新角色。
9. 长期支持：
   - 怪物模板
   - 模块 / 剧本摘要
   - 规则知识库与怪物百科
   - 更完整的 Rules Guard

## 3. 当前已经实现的内容

当前版本已经有一个可运行的最小闭环。

### 3.1 模型与运行链路

已经实现：

1. 后端使用 FastAPI。
2. 当前 DM 对话链路使用 LangGraph + LangChain 连接 OpenAI-compatible 模型。
3. 本地 `.env` 当前指向 Z.AI GLM-5.1，公开的 `.env.example` 只保留无密钥配置。
4. 游戏真相保存在本地 `GameState` JSON，而不是只存在模型上下文里。
5. Agent 已接入本地规则检索工具 `lookup_rules`。
6. RAG 已切换到 `Qwen/Qwen3-Embedding-4B-GGUF` + `llama.cpp` + Chroma 方案；LangGraph 每回合会先经过 `retrieve_rules` 节点注入少量带来源规则片段。缺少目标向量库时会明确标记未就绪，不再回退到旧的 markdown 词法检索。
7. Python 环境使用 conda 的 `DM_Agent` 虚拟环境。

### 3.2 角色与规则目录

已经实现：

1. 角色模板的本地保存与读取。
2. `Character` 模型包含物种、背景、起源专长、技能豁免、资源、法术、装备和重大经历。
3. 本地规则目录 `character_builder_2024.json`。
4. `RuleCatalog` 可提供：
   - 物种
   - 背景
   - 起源专长
   - 职业目录
   - 职业技能可选项
   - 起始法术位
   - 起始职业资源
   - 起始装备
5. 保存角色时会自动校验和补全起始资源、起始法术位、起始装备、金币和基础 AC。

### 3.3 跑团流程状态

已经实现：

1. `CampaignFlowState`
2. 游戏创建后自动进入 `adventure_selection`
3. 后端自动生成 3 个初始剧本摘要
4. 用户选择剧本后切换到 `exploration`

当前阶段包括：

- `character_creation`
- `party_creation`
- `adventure_selection`
- `exploration`
- `combat`
- `level_up`

### 3.4 怪物模板

已经实现：

1. `MonsterTemplate`
2. `MonsterStorage`
3. 怪物模板 API
4. Agent 可保存怪物模板
5. Agent 可从模板生成怪物并加入遭遇

### 3.5 战斗与动作

已经实现：

1. 最小 `EncounterState`
2. 先攻顺序
3. 当前行动者
4. 推进回合
5. HP 修改
6. 状态添加 / 移除
7. 攻击结算
8. 技能检定
9. 豁免检定
10. 施法合法性校验
11. 法术位消耗
12. 物品使用与数量扣除
13. 结束遭遇时统一生成结果摘要并写入 `adventure_log`
14. 本地动作接口会拒绝越过当前行动者的战斗动作
15. 攻击支持普通、非致命和俘获导向结算
16. 结构化状态支持证物、战利品、重大经历和章节总结写入

### 3.6 结构化时间线

已经实现：

1. `SessionEvent`
2. 每轮返回：
   - `history`
   - `history_append`
   - `timeline`
   - `timeline_append`
   - `tool_results`
   - `state_delta`
   - `game_state`

### 3.7 前端

前端当前已经能：

1. 调用规则目录接口。
2. 创建角色。
3. 创建怪物模板。
4. 创建并进入游戏。
5. 选择初始剧本。
6. 发送自由文本到 DM。
7. 从聊天侧栏执行本地动作：
   - 推进回合
   - 攻击
   - 施法
   - 技能检定
   - 豁免检定
   - 使用物品
8. 在攻击表单里从 `action-options.attacks` 自动同步攻击元数据。

## 4. 当前没有完成的内容

### 4.1 后端 Agent 编排仍需强化

原 `DMAgent` 使用 ADK 跑单回合，问题是：

1. 每回合新建 `InMemorySessionService`，没有真正使用持久 ADK session。
2. `GameState` 仍是本地权威状态，ADK session 只是临时承载。
3. 工具闭包强耦合 ADK `ToolContext`。
4. 阶段路由和工具权限主要靠 prompt 与工具内部校验，没有形成显式流程图。
5. 后续战斗、升级、RAG、章节推进会让单个 Agent 类越来越难控。

当前这些问题中的 ADK orchestration 已经移除，`DMAgent` 固定委托到 LangGraph。下一步应继续把 RAG、状态校验和更细的阶段分支做成显式图节点。

### 4.2 角色创建器仍不完整

还缺：

1. 更完整的 2024 角色构建规则。
2. 更清晰的起始装备展示。
3. 更清晰的起始资源展示。
4. 更清晰的起始法术位展示。
5. 更细的法术选择限制与 UI 提示。

### 4.3 战斗操作层仍偏原型

还缺：

1. 更完整的怪物动作自动映射。
2. 更好的施法选项展示。
3. 更好的资源耗尽反馈。
4. 更清晰的当前行动者操作约束提示。

### 4.4 Rules Guard 仍不完整

还缺：

1. 更完整的 2024 职业特性校验。
2. 更完整的专长校验。
3. 更完整的法术准备 / 已知规则。
4. 更完整的装备熟练、护甲影响与武器规则。
5. 升级规则。

### 4.5 长期跑团系统还没做完

还缺：

1. 升级模板与升级流程。
2. 更完整的经验 / 里程碑模式。
3. 长休 / 短休规则流。
4. 剧本管理与更多模块内容。
5. 更高质量的 RAG 切片、召回与排序。

## 5. 关键文件说明

### 5.1 后端核心

`backend/main.py`

FastAPI 路由入口，暴露角色、怪物、游戏、规则目录、剧本选择、遭遇和动作接口。

`backend/agent.py`

当前 LangGraph facade，处理 DM 文本回合入口并委托到 `DMGraphRunner`。

当前状态：原 ADK wrapper 和 `_build_tools()` 已删除，工具执行由 `backend/dm_graph.py` 的 `execute_tools` 节点委托到 `backend/agent_tools.py`。

`backend/agent_tools.py`

框架无关 Agent 工具层，当前包含 `AgentToolService` 与 `AgentToolExecution`。它接收显式 `GameState` 和工具参数，返回工具结果、时间线事件和状态 delta，不依赖编排框架 runtime。

`backend/dm_graph.py`

LangGraph workflow。当前包含 `prepare_turn`、`route_phase`、`prepare_context`、`draft_response`、`execute_tools`、`finalize_turn` 节点，用可选导入保护 LangGraph 依赖缺失场景。`route_phase` 当前负责写入 `phase`、`scene` 和 `allowed_tools`；`draft_response` 在 `enable_model=True` 时会调用 OpenAI-compatible `ChatOpenAI`，并在模型返回 tool calls 时路由到 `execute_tools`。

`backend/action_service.py`

不经过大模型的本地动作服务：

- 攻击
- 施法
- 技能检定
- 豁免检定
- 使用物品
- 推进回合
- 结束遭遇
- 结构化写入物品、重大经历与章节进度

`backend/game_logic.py`

本地游戏真相修改：

- 遭遇
- 先攻
- 回合推进
- HP
- 状态
- 怪物实例化
- 遭遇总结与结束
- 非致命 / 俘获结果

`backend/models.py`

主要数据模型：

- `Character`
- `MonsterTemplate`
- `GameState`
- `CampaignFlowState`
- `EncounterState`
- `SessionEvent`
- `TurnResult`

### 5.2 后端规则与数据

`backend/rules_catalog.py`

本地规则目录服务，是 Rules Guard 的第一层。

`backend/adventure_service.py`

初始冒险摘要生成逻辑。

`backend/library.py`

法术资料库读取。

`backend/rag.py`

Agent 规则检索层。运行时只读取 Qwen3-Embedding-4B-GGUF 构建的 Chroma collection；缺少依赖、数据库或非空 collection 时会返回未就绪状态。召回会多取候选，再按来源做轻量去重，并限制注入模型上下文的总长度。

当前 Chroma collection 默认为 `dnd_rules_qwen3_embedding_4b_q6_k`，query embedding 通过本地 `llama.cpp` OpenAI-compatible `/v1/embeddings` 接口生成，并在查询前统一补上 retrieval instruct 前缀。

`backend/rag_ingest.py`

离线构建或重建本地知识库索引。

默认读取 `backend/Documents/DND5e 2024`，把切片、来源路径和标题层级写入 `backend/Knowledge/vector_db`。完整构建建议在 CUDA 环境中运行：

```powershell
cd backend
$env:PYTHONNOUSERSITE="1"
$env:RAG_EMBEDDING_DEVICE="cuda"
python rag_ingest.py --reset
```

快速验证切片但不加载 GGUF 模型、也不写入 Chroma：

```powershell
cd backend
$env:PYTHONNOUSERSITE="1"
python rag_ingest.py --dry-run
```

当前默认切片为 512 字符、80 字符 overlap。全量 dry-run 统计为 2948 个源文件、19694 个 chunk；当前默认 collection `dnd_rules_qwen3_embedding_4b_q6_k` 已在本机构建完成。为保证中文规则 chunk 的稳定嵌入，默认 `RAG_LLAMA_SERVER_CTX` 建议保持 `4096`。无 CUDA 时脚本默认阻止大批量 CPU 构建；CPU 只建议做小批量 smoke test：

```powershell
cd backend
$env:PYTHONNOUSERSITE="1"
python rag_ingest.py --max-chunks 2 --reset --db-path Knowledge/vector_db_smoke --collection rag_smoke
```

非 `--reset` 运行会跳过 collection 中已有的 chunk id，可用于中断后续跑。`rag_manifest.json` 会记录 running/complete 状态、chunk 总数、已嵌入数量和跳过数量。

`backend/storage.py`

本地 JSON 持久化。当前目录约定：

- `backend/Characters`
- `backend/Monsters`
- `backend/Game`

这些目录是本地运行产物，不应该推送。

### 5.3 前端

`frontend/src/App.jsx`

当前所有页面和状态流集中在这里。后续可以逐步拆分，但不是 LangGraph 重构第一优先级。

`frontend/src/api.js`

前端 API 封装层。

`frontend/src/index.css` / `frontend/src/App.css`

页面样式。

`frontend/vite.config.js`

Vite 代理配置。

### 5.4 文档

`BACKEND_API_DESIGN.md`

后端 API 设计与 LangGraph 重构计划。

`FRONTEND_API_DESIGN.md`

前端 API 设计说明。

`Walkthrough.md`

当前交接文档。

`LOCAL_FRAMEWORK_DECISION.md`

本地框架决策记录，已加入 `.gitignore`，不进入仓库提交。

## 6. 当前主要接口一览

### 6.1 基础

- `GET /api/v1/health`
- `GET /api/v1/config`

### 6.2 规则与资料

- `GET /api/v1/rules/character-builder`
- `GET /api/v1/library/classes`
- `GET /api/v1/library/spells/{class_name}`
- `GET /api/v1/rag/status`
- `POST /api/v1/rag/search`

### 6.3 角色与怪物模板

- `GET /api/v1/characters`
- `POST /api/v1/characters`
- `GET /api/v1/characters/{identifier}`
- `GET /api/v1/monsters`
- `POST /api/v1/monsters`
- `GET /api/v1/monsters/{identifier}`

### 6.4 游戏流程

- `GET /api/v1/games`
- `POST /api/v1/games`
- `GET /api/v1/games/{game_id}`
- `GET /api/v1/games/{game_id}/action-options`
- `POST /api/v1/games/{game_id}/select-adventure`
- `POST /api/v1/games/{game_id}/turns`

### 6.5 遭遇

- `POST /api/v1/games/{game_id}/encounters/start`
- `POST /api/v1/games/{game_id}/encounters/add-enemy`
- `POST /api/v1/games/{game_id}/encounters/spawn-template`
- `POST /api/v1/games/{game_id}/encounters/end`
- `POST /api/v1/games/{game_id}/encounters/remove-combatant`
- `POST /api/v1/games/{game_id}/encounters/set-initiative`
- `POST /api/v1/games/{game_id}/encounters/roll-initiative`

### 6.6 本地动作

- `POST /api/v1/games/{game_id}/actions/advance-turn`
- `POST /api/v1/games/{game_id}/actions/attack`
- `POST /api/v1/games/{game_id}/actions/skill-check`
- `POST /api/v1/games/{game_id}/actions/saving-throw`
- `POST /api/v1/games/{game_id}/actions/cast-spell`
- `POST /api/v1/games/{game_id}/actions/use-item`

## 7. LangGraph 重构计划

### 7.1 重构目标

把当前：

```text
FastAPI -> DMAgent -> Google ADK LlmAgent -> ADK tools -> GameState
```

重构为：

```text
FastAPI -> DMAgent compatibility wrapper -> LangGraph DM workflow -> framework-neutral tools -> GameState
```

外部 API 尽量不变，内部编排变成可检查、可测试、可路由的图。

### 7.2 建议新增模块

`backend/dm_graph.py`

LangGraph workflow 定义。包含图状态、节点、边和编译后的 graph。

`backend/agent_tools.py`

框架无关工具函数。当前已落地，工具接收显式 `GameState` 和参数，返回统一的 `AgentToolExecution`。

`backend/dm_graph.py`

LangGraph workflow 定义。当前已固定接管 `/api/v1/games/{game_id}/turns`，`DMAgent` 不再保留 ADK 后端切换路径。

`backend/tool_registry.py`

工具注册表、阶段白名单、工具 schema 与工具名映射。

`backend/agent_runtime.py`

可选。封装模型创建、消息转换、工具调用循环、运行配置。

### 7.3 建议图节点

`prepare_turn`

- 复制 `GameState`
- 添加玩家事件
- 初始化图状态

`route_phase`

- 根据 `campaign.phase`、`scene`、`encounter.active` 选择路径

`prepare_context`

- 构造状态摘要和近期历史

`retrieve_rules`

- 每回合按用户输入查询本地 RAG，默认取 3 条片段

`call_dm_model`

- 调用 OpenAI-compatible chat model
- 暴露当前阶段允许的工具

`execute_tool_calls`

- 调用框架无关工具
- 写回 `tool_results`、`state_delta`、`timeline_append`

`validate_state`

- 统一校验战斗、资源、法术位、物品、状态变化

`finalize_turn`

- 追加 DM 回复
- 更新聊天历史
- 返回 `TurnResult`

### 7.4 阶段工具白名单

探索阶段可用：

- `lookup_rules`
- `roll_dice`
- `append_adventure_log`
- `add_inventory_item`
- `record_major_experience`
- `record_chapter_progress`
- `set_scene`
- `set_active_character`
- `start_encounter`
- `save_monster_template`

战斗阶段可用：

- `lookup_rules`
- `roll_dice`
- `adjust_hp`
- `add_status`
- `remove_status`
- `set_defeat_state`
- `add_enemy`
- `spawn_monster_from_template`
- `attack_target`
- `roll_skill_check`
- `roll_saving_throw`
- `cast_spell`
- `set_initiative`
- `roll_initiative`
- `advance_turn`
- `end_encounter`

升级阶段后续再设计，不应复用探索 prompt 粗暴处理。

### 7.5 分阶段执行

Phase 1: 工具拆分

- 从 `agent.py` 中拆出工具实现。
- 工具不依赖编排框架 runtime。
- HTTP API 契约保持不变。

当前状态：Phase 1A、Phase 1B 和 Phase 2G 已完成。原 ADK wrapper 已删除，LangGraph 工具节点直接调用 `AgentToolService`。

Phase 2: LangGraph 单回合等价链路

- 新增 `dm_graph.py`。
- 保持 `DMAgent.run_turn(state, user_input)` 签名不变。
- 让 `/turns` 返回结构保持兼容。

当前状态：Phase 2A 已完成。`DMGraphRunner` 已有最小 workflow 骨架。

补充状态：Phase 2B 已完成。依赖已声明并安装到本地 `DM_Agent` conda 环境，`DMGraphRunner` 已能创建真实模型节点。

补充状态：Phase 2C 已完成。LangGraph runner 已能绑定 26 个工具 schema，按场景生成 `allowed_tools`，执行 tool calls 并把工具结果、时间线事件和状态 delta 合并回图状态。

补充状态：Phase 2D 已完成。`route_phase` 已从 `prepare_turn` 中拆出，成为独立图节点，后续可以从这里扩展探索、战斗、升级分支。

补充状态：Phase 2E 已完成。非战斗阶段工具白名单保留检定、豁免、施法、HP 与状态变化等常见规则结算能力；战斗阶段再额外暴露攻击、先攻、推进回合和结束遭遇工具。

补充状态：Phase 2F 已完成。真实 GLM-5.1 smoke test 已通过：普通探索回合可以返回模型文本，要求模型调用 `roll_dice` 的回合可以产生 `dice.roll` 工具结果并写入时间线。模型节点已经恢复为直接调用 `model.invoke(...)`，不再做 provider 异常兜底。

补充状态：Phase 2G 已完成。`agent.py` 已删除 ADK orchestration 和 `_build_tools()`，`DMAgent` 固定委托到 LangGraph；`backend/requirements.txt` 已移除 `google-adk` 与 `litellm`。

Phase 3: 显式阶段路由

- 按 `campaign.phase` 和 `scene` 分支。
- 按阶段限制工具。
- 战斗流程单独收束。

Phase 4: RAG 与 Rules Guard 强化

- 把 RAG 变成图中的可观察节点。
- 控制规则片段长度、来源和注入位置。
- 工具调用失败时让模型有机会修正。

补充状态：Phase 4A 已完成。`backend/rag_ingest.py` 已切换为 Qwen3-Embedding-4B-GGUF ingestion，并提供 `--dry-run`、CPU 大批量保护、manifest 进度记录和续跑能力；本地全量 dry-run 已确认 2948 个源文件会生成 19694 个 chunk；官方 `Qwen3-Embedding-4B-Q6_K.gguf` 已下载，配合本地 `llama.cpp` CUDA 版 runtime 已在 RTX 3060 Laptop 6GB 上完成验证，并已成功构建默认 collection `dnd_rules_qwen3_embedding_4b_q6_k`；`backend/rag.py` runtime 检索使用同一 embedding 模型且不再保留 `rg` fallback；`DMGraphRunner` 已加入 `retrieve_rules` 节点。

Phase 5: 可恢复执行和观测

- 评估 LangGraph checkpointer。
- 记录 graph run id / thread id。
- 加强节点级日志和错误定位。

## 8. 已验证内容

此前已经跑过并通过的验证包括：

1. `python -m compileall backend`
2. `npm run build`
3. 角色创建接口 smoke test
4. 游戏创建与初始剧本选择 smoke test
5. 施法合法性 smoke test
6. 本地动作接口 smoke test
7. 起始装备 / 资源与自动推导攻击项 smoke test
8. 结束遭遇摘要与 `adventure_log` 一致性 smoke test
9. 先攻顺序与当前行动者一致性 smoke test
10. 非致命击倒与遭遇总结分类 smoke test
11. 证物 / 重大经历 / 章节记录落库 smoke test

LangGraph 重构每完成一个阶段，都至少要重新跑：

1. `python -m compileall backend`
2. `cd frontend && npm run build`
3. `/turns` 普通探索回合
4. 开始遭遇、攻击、推进回合
5. 施法消耗法术位
6. 结束遭遇并写入 `adventure_log`
7. RAG 查询

## 9. 已知问题与注意事项

### 9.1 前端主文件较大

`frontend/src/App.jsx` 当前是单文件大组件。后续继续开发时最好逐步拆分，但不要和后端 LangGraph 重构混在同一个大改里。

### 9.2 PowerShell 中文显示可能乱码

PowerShell / conda 在某些输出场景会有编码噪声，但不影响核心逻辑。读写文档时优先保持 UTF-8。

### 9.3 法术资料库职业名存在历史兼容问题

后端已通过 `RuleCatalog.resolve_spell_library_key()` 做映射兼容，不要直接假定法术库里的职业 key 与前端展示名一致。

### 9.4 action-options 仍可继续丰富

目前已经能返回攻击项、法术、物品、资源，但前端还没有完全自动填满所有动作表单。

### 9.5 后端修改保持短注释风格

当前后端 Python 文件已经有一层简短注释。后续继续开发时：

- 每个模块有一句职责说明。
- 复杂状态同步、战斗流程、持久化写入前后补一句简短注释。
- 注释解释为什么这样做，不重复代码字面含义。

## 10. 下一步最应该做什么

优先级建议：

1. **继续完成 LangGraph 单回合 runner。**
   - 做真实模型回合 smoke test。
   - 验证探索和战斗工具调用都能稳定回写 `GameState`。
   - `TurnResult` 响应保持兼容。
2. 做阶段路由和工具白名单。
   - 探索、战斗、升级拆开。
   - 战斗工具受当前行动者约束。
3. 再继续优化 RAG。
   - 改善 query 重写、召回排序和片段截断。
   - 在已完成的 D&D 2024 规则库基础上，逐步接入怪物百科与模块文本。
4. 后续再处理升级模板、前端拆分和完整 Rules Guard。

## 11. 下次进入仓库后的建议第一步

建议下次先做：

1. 打开 `BACKEND_API_DESIGN.md` 和 `Walkthrough.md`。
2. 阅读：
   - `backend/agent.py`
   - `backend/action_service.py`
   - `backend/game_logic.py`
   - `backend/models.py`
   - `backend/rag.py`
3. 确认本地状态：
   - `git status --short`
   - `python -m compileall backend`
   - `cd frontend && npm run build`
4. 从 `backend/dm_graph.py` 的阶段路由、RAG 节点和状态校验继续推进。

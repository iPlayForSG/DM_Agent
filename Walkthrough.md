# DM_Agent Walkthrough

## 1. 文档用途

这是一份给后续开发者或 Agent 使用的项目交接文档。

目标：

1. 说明项目最终要实现什么。
2. 说明当前代码已经做到哪里。
3. 说明下一步最应该做什么。
4. 说明仓库里关键文件分别负责什么。
5. 说明如何在本地继续运行、验证和扩展。

当前下一阶段重点：**继续强化 LangGraph 后端 Agent 编排，并逐步整理前端单文件界面结构**。

最新进展：已经完成 Phase 1A、Phase 1B、Phase 2A、Phase 2B、Phase 2C、Phase 2D、Phase 2E、Phase 2F 和 Phase 2G。`backend/agent_tools.py` 已承载框架无关工具层；`backend/agent.py` 已变为 LangGraph-only facade；`backend/dm_graph.py` 已加入 LangGraph runner、OpenAI-compatible 模型节点、工具调用循环、独立 `route_phase` 节点和第一版阶段化工具白名单；OpenAI-compatible 后端下的普通回合与 `roll_dice` 工具回合 smoke test 已通过。最近一轮又把角色创建器改成了多步向导，并补了两端约束：起源专长明确固定到背景、自定义购买起始装备、自定义待定装备、27 点购点属性校验、level 1 生命值自动推导与强校验、起始装备预算占用与金币回写。

当前本地模型通过 OpenAI-compatible 接口接入，具体模型和 base URL 由 `backend/.env` 决定，可以随时切换。真实 API key 只在 `backend/.env` 中保存，该文件被 `.gitignore` 忽略，不能提交或推送。

记住：每次修改代码后，都要在本地 git commit，并编写一条英文 message。同时，如果有必要，同步更新 BACKEND_API_DESIGN.md、FRONTEND_API_DESIGN.md、Walkthrough.md，以保证项目结构清晰。

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
3. 本地 `.env` 通过 OpenAI-compatible 接口指向当前选用的模型，公开的 `.env.example` 只保留无密钥配置。
4. 游戏真相保存在本地 `GameState` JSON，而不是只存在模型上下文里。
5. Agent 已接入本地规则检索工具 `lookup_rules`。
6. RAG 已切换到 `Qwen/Qwen3-Embedding-4B-GGUF` + `llama.cpp` + Chroma 方案；LangGraph 每回合会先做规则意图分类，再通过 `retrieve_rules` 节点规划多条 query 注入少量带来源规则片段，当前已覆盖规则问答、施法裁定、战斗裁定、状态裁定、技能裁定和休息恢复。缺少目标向量库时会明确标记未就绪，不再回退到旧的 markdown 词法检索。
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
9. 在 `New Game` 页面真正提交已选队伍角色，建局成功后直接消费 `POST /api/v1/games` 返回的 `game_state` 与 `action_options`。
10. 优先消费后端返回的 `*_display` 字段，在职业、法术、物品、伤害类型、状态和怪物摘要上默认显示中文。
11. 首页、新建游戏弹窗、遭遇侧栏与状态页已经做过一轮中文化与响应式布局调整。
12. 前端 API 层优先使用 `VITE_BACKEND_URL/api/v1` 直连运行时后端地址，网络失败时返回中文错误提示。
13. 角色构筑页全部背景（如 Farmer / Sage / Soldier / Wayfarer）、全部起源专长（包括三种 Magic Initiate 变体以及 Crafter / Lucky / Savage Attacker / Skilled / Tough）、所有职业起始装备包与二级选项、起始装备明细与职业资源、技能选择都会显示为中文；对于后端按键名索引的资源（如 `Wild Shape`、`Lay on Hands`），前端补了 `localizeClassResource` 映射。
14. 角色构筑页不再把全部字段堆在一个页面，而是拆成“基础 / 构筑 / 装备 / 法术 / 总览”五步。
15. 起始装备新增 `equipment_mode` 分支：标准套装、自定义购买、自定义待定装备；后端会按预算物化最终 `inventory` 与 `gold_gp`。
16. 属性和生命值约束前移：前端按 27 点购点限制 8-15，后端再做同样校验；level 1 `hp_max` 改为职业生命骰 + 体质修正自动推导。
14. 页面主滚动条统一由 `main-content` 承担，`home-container` / `creator-container` 不再各自滚动，滑块始终贴紧浏览器最右侧。

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
2. 更完整的高级职业特性与多职业支持。
3. 更细的法术选择限制与 UI 提示。
4. 更完整的装备、资源与法术说明文本。

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

当前 Chroma collection 默认为 `dnd_rules_qwen3_embedding_4b_q6_k`，query embedding 通过本地 `llama.cpp` OpenAI-compatible `/v1/embeddings` 接口生成，并在查询前统一补上 retrieval instruct 前缀。RAG runtime 现已支持多 query 合并召回和轻量本地重排，供 LangGraph 自动规则注入复用。

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

前端 API 封装层。当前支持 `VITE_BACKEND_URL` 直连回退，并在网络不可达时抛出中文错误。

`frontend/src/index.css`

当前主要页面样式，包括首页卡片区、新建游戏弹窗、聊天布局与状态页响应式规则。

`frontend/src/App.css`

历史 Vite scaffold 样式文件，当前不是主要样式入口，后续可以视情况清理。

`frontend/vite.config.js`

Vite 代理配置。

`start.ps1` / `start.cmd`

Windows 启动入口。`start.ps1` 会自动选择可用端口、写入 `frontend/.env.development.local` 的 `VITE_BACKEND_URL`，并同时拉起前后端；`start.cmd` 是可双击的薄包装器。

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

补充说明：`POST /api/v1/games` 当前会直接返回 `game_state` 和 `action_options`，供前端建局后直接进入冒险选择界面。

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

- 每回合先做规则意图分类，再决定是否查询本地 RAG，默认取 3 条片段
- query planning 会复用 `scene`、`phase`、主动角色、法术名和规则关键词，而不是只搜用户原句

`call_dm_model`

- 调用 OpenAI-compatible chat model
- 暴露当前阶段允许的工具

`execute_tool_calls`

- 调用框架无关工具
- 写回 `tool_results`、`state_delta`、`timeline_append`

`validate_state`

- 统一校验战斗、资源、法术位、物品、状态变化
- 同步 party combatant 镜像，修复先攻顺序和当前行动者
- 敌方全部失去行动能力时自动结束遭遇，并补写 `adventure_log` 与 timeline event

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

补充状态：Phase 2F 已完成。在 OpenAI-compatible 后端上跑通过 smoke test：普通探索回合可以返回模型文本，要求模型调用 `roll_dice` 的回合可以产生 `dice.roll` 工具结果并写入时间线。模型节点已经恢复为直接调用 `model.invoke(...)`，不再做 provider 异常兜底；运行时具体使用的模型由 `.env` 中的 `LLM_MODEL` 决定，可以随时切换。

补充状态：Phase 2G 已完成。`agent.py` 已删除 ADK orchestration 和 `_build_tools()`，`DMAgent` 固定委托到 LangGraph；`backend/requirements.txt` 已移除 `google-adk` 与 `litellm`。

Phase 3: 显式阶段路由

- 按 `campaign.phase` 和 `scene` 分支。
- 按阶段限制工具。
- 战斗流程单独收束。

Phase 4: RAG 与 Rules Guard 强化

- 把 RAG 变成图中的可观察节点。
- 控制规则片段长度、来源和注入位置。
- 工具调用失败时让模型有机会修正。

补充状态：Phase 4A 已完成。`backend/rag_ingest.py` 已切换为 Qwen3-Embedding-4B-GGUF ingestion，并提供 `--dry-run`、CPU 大批量保护、manifest 进度记录和续跑能力；本地全量 dry-run 已确认 2948 个源文件会生成 19694 个 chunk；官方 `Qwen3-Embedding-4B-Q6_K.gguf` 已下载，配合本地 `llama.cpp` CUDA 版 runtime 已在 RTX 3060 Laptop 6GB 上完成验证，并已成功构建默认 collection `dnd_rules_qwen3_embedding_4b_q6_k`；`backend/rag.py` runtime 检索使用同一 embedding 模型且不再保留 `rg` fallback，并已加入多 query 合并召回与轻量本地重排；`DMGraphRunner` 已加入 `retrieve_rules` 节点，并已实现规则敏感输入判定、多 query planning、回合内规则片段 prompt 注入和工具执行后的最小状态校验；最新一轮又补上了先攻顺序整理、自动启动回合序列和验证备注回灌消息流。这一轮继续把自动检索改成显式规则意图分类，并让 `validate_state` 在敌方全部失去行动能力时自动结束遭遇、写回 `adventure_log` 并追加自动结束事件。

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
12. `POST /api/v1/games` 建局后直接返回状态快照 smoke test
13. 前端中文化和动态后端地址回退后的 `npm run build`

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

### 9.5 前端已中文化，但组件仍未拆分

当前中文界面和显示字段链路已经能工作，但 `frontend/src/App.jsx` 仍是单文件大组件，后续调整 UI 或联调时要避免在一个 commit 里同时混入大规模结构重排和后端行为修改。

### 9.6 后端修改保持短注释风格

当前后端 Python 文件已经有一层简短注释。后续继续开发时：

- 每个模块有一句职责说明。
- 复杂状态同步、战斗流程、持久化写入前后补一句简短注释。
- 注释解释为什么这样做，不重复代码字面含义。

## 10. 下一步最应该做什么

优先级建议：

1. **继续细化 LangGraph 阶段分支、状态校验和 Rules Guard。**
   - 探索、战斗、升级拆开。
   - 继续补齐显式状态修复与非法工具调用反馈。
2. 逐步拆分前端单文件页面。
   - 优先拆 `App.jsx` 中的新建游戏、聊天侧栏和状态页。
   - 保持现有中文显示字段链路不回退。
3. 再继续优化 RAG。
   - 在已完成自动规则注入的基础上，继续改善 query 重写、召回排序和片段截断。
   - 在已完成的 D&D 2024 规则库基础上，逐步接入怪物百科与模块文本。
4. 后续再处理升级模板和完整 Rules Guard。

## 10. 2026-05-07 Workflow Update

- `backend/dm_graph.py`
  - `route_phase` 现在会做 canonical phase normalization，而不是只回填当前 `campaign.phase`/`scene`。
  - 已新增 phase policy 表：`party_creation`、`character_creation`、`adventure_selection`、`exploration`、`combat`、`downtime`、`level_up` 都有独立工具白名单、目标和约束。
  - 已新增轻量 `turn_profile`，把回合进一步分成 `setup_guidance`、`conversation`、`rules_reference`、`action_resolution`、`combat_resolution`，用来限制工具数量和工具回合预算，避免简单对话被重型流程拖慢。
  - 已新增确定性的 `turn_advice`，会把回合预期、建议工具和简短 checklist 注入 prompt，并把建议工具排到 allowed tools 前面，减少模型试探。
  - `prepare_context` 会把 phase objective / constraints / blockers 注入 prompt。
  - `validate_state` 会在工具执行后再次复用 phase normalization，避免状态漂到非法阶段。
- `backend/prompts.py`
  - `build_dm_instruction()` 现在显式接收 workflow phase 指南和 turn profile 指南，不再只依赖 state summary。
- `tests/test_dm_graph_workflow.py`
  - 已补 phase workflow 回归测试，覆盖未完成 setup 的冒险选择回退、combat 强制恢复、level-up 工具约束、社交问句保持轻量 profile、纯规则问句只开放 `lookup_rules`，以及 prompt 注入检查。

这意味着下一轮如果继续完善 Agent 工作流，优先级应该放在“低摩擦规划/执行分离”和“整章级回放测试”，而不是盲目增加更多节点。

## 11. 下次进入仓库后的建议第一步

建议下次先做：

1. 打开 `BACKEND_API_DESIGN.md` 和 `Walkthrough.md`。
2. 如果要直接联调前后端，优先运行 `start.ps1`，或者直接双击 `start.cmd`。
3. 阅读：
   - `backend/agent.py`
   - `backend/action_service.py`
   - `backend/game_logic.py`
   - `backend/models.py`
   - `backend/rag.py`
4. 确认本地状态：
   - `git status --short`
   - `python -m compileall backend`
   - `cd frontend && npm run build`
5. 从 `backend/dm_graph.py` 的阶段路由、RAG 节点和状态校验，或从 `frontend/src/App.jsx` 的组件拆分继续推进。
## 12. 2026-05-08 Agent Workflow Review And Persistence Step

这一轮重新对照了 Anthropic / OpenAI / LangGraph / MCP / A2A 的官方资料后，结论不是“马上多 agent 化”，而是先把当前单 agent workflow 做成更稳的生产形态。现阶段最缺的不是更多节点，而是：

- checkpoint / resume
- input-required 中断语义
- trace 级可观测性
- 长章节上下文编译
- 流式 turn 生命周期

基于这个判断，已经先落了最小的一步：

- `backend/dm_graph.py`
  - Graph 现在会在可用时带 `InMemorySaver` checkpointer 编译。
  - 在 `prepare_turn` 和 `route_phase` 之间新增了一个最小 `input_gate` 节点。
  - 空输入会直接暂停为 `input_required`。
  - 在 `adventure_selection` / `combat` 阶段，过于泛化的“继续 / 开始 / 就这样”也会要求玩家补充明确动作。
- `backend/models.py`
  - `GameState` 新增 `pending_turn`，用于保存等待补充输入的暂停态。
  - `TurnResult` 新增 `turn_status` 和 `pending_input`，让前端和调试层能区分“回合完成”与“回合暂停等待补充说明”。
- `backend/main.py`
  - `POST /api/v1/games/{game_id}/turns` 现在会自动识别 `pending_turn`。
  - 如果存在未完成暂停回合，同一个接口会自动走恢复执行，不要求前端先改成另一条专用恢复接口。
- `tests/test_dm_graph_workflow.py`
  - 已补最小回归：空输入触发 `input_required`，以及补充说明后同回合恢复完成。

这一步的边界也要记清楚：

- 现在的 LangGraph checkpointer 还是 `InMemorySaver`。
- 它能证明 pause/resume 链路已经接通，但还不是跨进程、跨重启的 durable execution。
- 也就是说：当前实现是“最小可工作的 workflow pause/resume”，不是最终版持久化任务系统。

下一步优先级建议保持不变，但顺序更明确：

1. 把 in-memory checkpointer 替换成 SQLite / Postgres 这类真正可恢复的持久化 saver。
2. 给 turn 执行补 SSE 生命周期事件，而不是继续维持整包阻塞返回。
3. 在现有 `phase + turn_profile + turn_advice` 之上，再补一层极小 typed intent。
4. 做 trace logging 和整章 replay eval。

暂时不要做的事也仍然成立：

- 不要先冲多 agent / A2A。
- 不要先把 planner 做成很重的多轮 evaluator loop。
- 不要继续只靠 prompt 堆更多控制逻辑而不补 runtime 层的可恢复性。

## 13. 2026-05-08 Durable Checkpoint Follow-Up

上一节里把 pause/resume 跑通后，下一步已经继续落地：

- `backend/dm_graph.py`
  - 默认 checkpointer 不再优先走 `InMemorySaver`，而是优先走 SQLite。
  - 默认 checkpoint 文件在 `backend/Game/langgraph_checkpoints.sqlite`。
  - 如果 `langgraph-checkpoint-sqlite` 缺失，或 SQLite 初始化失败，会自动降级回 `memory`，同时写出运行时 warning。
  - `DMGraphRunner` 现在会暴露 `checkpoint_backend`、`checkpoint_db_path` 和 `checkpoint_warning`，并支持显式关闭底层连接。
- `backend/main.py`
  - `GET /api/v1/health` / `GET /api/v1/config` 现在都能直接看到当前 checkpoint backend 是 `sqlite` 还是 `memory`。
  - FastAPI shutdown 时会主动关闭 DM agent 底层 checkpoint 连接。
- `tests/test_dm_graph_workflow.py`
  - 已新增一条真正的持久化回归：先用一个 runner 触发 `input_required`，再用新的 runner 实例从同一个 SQLite checkpoint 文件恢复并完成回合。

这意味着当前状态已经从“最小 pause/resume 原型”进入“本地 durable checkpoint 初版”：

- 能跨 runner 实例恢复
- 能跨保存的 `pending_turn` 状态恢复
- 默认不会再因为单次进程内对象丢失而彻底失去 checkpoint

但也要明确边界：

- 现在仍然是本地 SQLite，本质上是单机开发/测试级 durable execution。
- 还没有接 SSE 事件流，所以前端体感上仍是阻塞式整包返回。
- 还没有做 trace 级审计，所以“为什么这一步暂停/恢复/走了哪些工具”仍然缺完整观测面。

下一步优先级现在收敛成：

1. SSE turn lifecycle
2. trace logging + replay eval
3. 极小 typed intent
4. 若要走真正生产部署，再考虑 Postgres checkpointer

## 14. 2026-05-08 Streaming Turn Lifecycle Step

SQLite checkpoint 打通后，下一步已经继续推进到了最小 SSE 生命周期：

- `backend/main.py`
  - 新增 `POST /api/v1/games/{game_id}/turns/stream`
  - 这个接口不会替换现有 `/turns`，而是保留兼容同步返回，同时提供 `text/event-stream` 版本给前端渐进接入
  - 当前事件顺序是：
    - `turn.started`
    - `turn.completed` 或 `turn.input_required`
    - `turn.saved`
    - `turn.finished`
    - 失败则是 `turn.error`
- 这一步仍然刻意保持克制：
  - 不额外新增 planner 节点
  - 不把每个 tool call 都拆成单独 SSE
  - 不改现有 `TurnResult` 契约
  - 只是把原本一次性整包返回的回合，先拆成“前端可见的最小生命周期”
- 测试层新增了接口级回归：
  - 校验 SSE 事件顺序
  - 校验同步 `/turns` 在有 `pending_turn` 时仍会自动走恢复路径

当前边界：

- 还没有做 heartbeat
- 还没有流出工具中间态
- 还没有流出 RAG 中间态
- 前端还没真正消费 SSE，只是后端接口和契约先准备好

因此下一步优先级继续收敛为：

1. trace logging
2. chapter replay eval
3. 极小 typed intent

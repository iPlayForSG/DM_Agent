# 模块地图

## 后端入口与编排

| 模块 | 目的/对外接口 | 主要依赖 | 修改时联动检查 |
| --- | --- | --- | --- |
| `backend/main.py` | `/api/v1/*`、SSE、错误映射、存档事务 | agent facade、storage、action service | `models.py`、`frontend/src/api.js`、API 契约测试 |
| `backend/player_projection.py` | REST/SSE 玩家投影：过滤普通暗骰载荷，类型化骰点记录明确保留明暗骰 | JSONResponse、RollRecord、序列化 payload | 游戏加载、turn、traces、局部动作，内部状态不得被删改 |
| `backend/agent.py` | 模型档案、Agent 生命周期、turn/resume facade | `dm_graph.py`、dotenv | health/config API、密钥脱敏、provider smoke |
| `backend/model_backends.py` | OpenAI-compatible/Claude Code/Codex provider 常量与 CLI `BaseChatModel` 适配 | LangChain、CLI subprocess | 临时目录、结构化 schema、凭据隔离、真实 CLI smoke |
| `backend/codex_transport.py` | 临时只读 app-server 会话、真实公开正文 delta、超时与进程清理 | Codex JSON-RPC、subprocess | 本机协议、无宿主工具、无私有推理输出、adapter、真实流式验证 |
| `backend/dm_graph.py` | LangGraph 父图、模型调用、暂停恢复、事务提交 | agents、dm_workflow、models | interrupt、trace、workflow tests |
| `backend/dm_workflow/` | planning 与 policies 决定能力，context 装配上下文，validation 校验与修复，tool_schemas 定义模型工具契约 | agents/specs、GameState、规则与记忆服务 | 工具所有权、预算、注册、回合测试 |
| `backend/combat_feedback.py` | Agent与本地武器/法术攻击的命中、重击及实际伤害骰式文案 | 已结算攻击result | 只展示结果，不重复掷骰或改伤害 |
| `backend/combat_flow.py` | 本次对话的玩家行动者、DM 连续结算及玩家决策交接 | GameState、GameLogic | 图状态、工具适配器、控制切换、多人回归 |
| `backend/agents/` | 持续 DM 私有循环、阶段能力、工具适配 | LangChain/LangGraph、tool registry | `specs.py` capability、runtime topology tests |

逐端点清单不在 memory 中重复维护：后端定义以 `backend/main.py` 的 FastAPI 路由和 `backend/models.py` 的 schema 为准；浏览器消费契约以 `frontend/src/api.js` 和相关 API 测试为准。

## 规则与状态

| 模块 | 目的/对外接口 | 主要依赖 | 修改时联动检查 |
| --- | --- | --- | --- |
| `backend/models.py` | `Character`、`EncounterState`、`GameState`、请求/响应 schema | Pydantic | JSON 兼容、API、前端字段、rewind、测试 fixture |
| `backend/world_state.py` | 世界条目、关联、时钟、见闻、私有上下文与查询 | Pydantic、GameState | dm_workflow 工具契约、AgentToolService、player_projection、时间线、rewind |
| `backend/tool_registry.py` | 工具 schema、风险和运行前守卫 | models、rules catalog | agent specs、phase allowlist、tool tests |
| `backend/agent_tools.py` | Agent 工具执行与统一 `ToolResult` | GameLogic、RuleCatalog | action service 对称行为、timeline、delta |
| `backend/action_service.py` | 本地动作 API 的确定性执行 | GameLogic、RuleCatalog | agent tool 行为、main routes、action options |
| `backend/spell_resolution.py` | 共用目标/资源/效果原子结算和 cast_id 法术攻击入口 | GameLogic、RuleCatalog、SpellAttackCast | Agent/本地动作、工具 guardrail、法术目标 UI、回合边界 |
| `backend/spell_effects.py` | 数据驱动的来源效果、豁免、数值修正、事件与时间清理 | ActiveSpellEffect、GameLogic、RollRecord | 施法/伤害/回合/非战斗时间、所有权、失败回滚与存档 |
| `backend/library.py`、`backend/data/spell_catalog_2024.json` | 单一完整中文法术资料、英文/历史名称兼容 | 本地2024手册、aliases、中文来源字段 | 建卡、法术说明、规则解析、刷新进程缓存 |
| `backend/utils/merge_spell_catalogs.py` | 离线合并旧法表：字段补全、别名合并、ID/环级冲突检查 | 主目录、显式历史输入 | 单一资料源、幂等生成、旧提取器 |
| `backend/utils/translate_spell_catalog.py` | 0至9环中文源文提取、双语清理、覆盖/漏译审计与可重复目录生成 | 指定本地法术详述、目录 | 数值/表格保真、旧名称兼容、英文导入器 |
| `backend/spell_rules.py`、`backend/data/spell_effect_rules.json` | 受信的声明式法术规则数据及能力边界 | Library、本地规则数据 | 目标/豁免/效果执行、明确拒绝未知机制 |
| `backend/scene_actors.py` | 非战斗NPC登记和遭遇身份迁移 | GameState.scene_actors、Combatant | 目标查找、存档、进入先攻、状态投影 |
| `backend/action_preflight.py`、`backend/resolution_protocol.py` | 复合施法只读检查及失败操作待办 | 规则目录、工具适配器、DMGraph | 提交守卫、规则反馈、事务回滚 |
| `backend/combat_status.py` | 只读状态栏投影：增益、减益、专注、来源与期限 | GameState、Library、spell effects | action-options 版本、角色/战斗员 UI、旧专注记录 |
| `backend/game_logic.py` | 骰子、攻击、伤害、先攻、镜像同步 | models | current actor、action ledger、concentration、combat tests |
| `backend/stealth_rules.py` | Hide 来源状态、DC15 隐匿、主动/被动察觉、失效及优劣势合并 | GameLogic、RuleCatalog、HidingState | Agent 工具/阶段能力、进战与攻击/言语施法、角色镜像、REST/SSE、旧存档 |
| `backend/inventory_narration.py` | 已提交库存（含钱币）差值与权威叙事标记 | GameState、Counter | finalize/长度后处理、失败回滚、前端语义强调 |
| `backend/roll_capture.py` | 请求局部实际骰点观察、工具成败与回合结算标记 | RollRecord、turn_stream | game_logic、ability_scores、dm_graph、main 消息/暂停持久化、玩家投影 |
| `backend/encounter_math.py` | 遭遇 XP 预算、难度分级、CR 估算（纯计算，无状态） | 无 | 只读工具 payload、5e.tools 表格出处、`test_encounter_math.py` |
| `backend/item_effects.py` | 已收录消耗品数值、物品规则引用与卷轴效果说明（只读，不执行效果） | starter shop、Library、InventoryItem | 拾取/schema、旧库存投影、治疗/伤害字段、不同环级叠放保护 |
| `backend/resource_rule_text.py`、`backend/data/class_resource_text_2024.json` | 职业资源原文的只读展示投影，按职业/子职/等级附加 rules_text 与出处 | 本地手册原文目录、import_resource_rule_text.py | 旧角色说明刷新、资源悬停、计数不变 |
| `backend/class_resources.py` | 按职业/等级派生基础资源与一次性旧角色迁移，保留已消耗量和自定义资源 | 成长表、最终属性、class_resource_version | 建卡、模板/存档/rewind加载、资源说明和基础消耗 |
| `backend/level_creation.py` | 单职业1–20级建卡配置、固定生命成长、升级属性与子职业/法术选择校验 | level_progression_2024.json、RuleCatalog、Character.base_stats | 只读creation-options API、角色保存、Agent建卡、等级回归 |
| `backend/rules_catalog.py` | 构筑目录、派生值、法术/装备校验 | JSON catalog、ability service | builder API、角色保存、攻击/法术工具 |
| `backend/ability_scores.py` | 购点、标准数组、4d6 去最低和记录验证 | RuleCatalog constants | builder UI、Character schema、相关测试 |

## 内容、存储与检索

| 模块 | 目的/对外接口 | 修改时联动检查 |
| --- | --- | --- |
| `backend/storage.py` | 原子 JSON 写入、state_version 冲突检查、文件锁与回合/rewind 提交 | schema 兼容、跨进程冲突、失败保留、delete/rewrite API |
| `backend/adventure_service.py` | 固定/AI 冒险生成与 D&D 风格校验 | setup flow、campaign schema、测试 |
| `backend/campaign_memory.py` | 从 `GameState` 派生有界的剧情提示上下文，不另存业务事实 | `dm_graph.py` memory context、prompts、工作流测试 |
| `backend/utils/import_5etools_builder_options.py` | 从本地 5e.tools 数据增量补齐建卡目录；幂等、只追加 | `character_builder_2024.json`、`validate_character`、builder API |
| `backend/rag.py` | 默认词法、显式向量模式及失败降级、多查询、来源去重与上下文截断 | health/status、dm_graph rules stage、`lexical_rag.py` |
| `backend/lexical_rag.py` | heading-aware Markdown/text 词法索引 | 规范化语料、中文/英文术语、fallback tests |
| `backend/rule_document_normalizer.py`、`backend/utils/normalize_rule_documents.py` | 原始规则书只读规范化、重复标题消歧、可继承目录 aliases、manifest quality warnings | `docs/RULE_DOCUMENT_STANDARD.md`、ignored corpus、检索质量抽查 |
| `backend/rag_embeddings.py` | GGUF 定位、跨平台 llama-server 生命周期、embedding | Windows/macOS 路径、CUDA/Metal/CPU、超时与日志 |
| `backend/rag_ingest.py` | 将本地规则文档切片并写入 Chroma 索引 | `rag_embeddings.py`、源目录、collection/manifest、构建命令 |

规则结算补充入口：`backend/weapon_use.py` 统一持有物的近战、投掷与临时武器模式；`backend/d20_bonuses.py` 处理来源授予骰、失败后选择和暂停随机恢复。修改时联动 `GameState`、动作API/工具schema、`roll_capture.py`、`player_projection.py` 与状态投影。

`backend/money.py` 统一库存钱币、整数铜币运算及旧金币字段迁移；修改时联动Character、建卡余额、adjust_currency工具/API、库存叙事与保存/回退测试，不维护第二份钱包余额。

## 前端

| 模块 | 目的/对外接口 | 修改时联动检查 |
| --- | --- | --- |
| `frontend/src/api.js` | API base URL、REST、SSE parser、错误标准化 | `main.py` 路由和响应 schema |
| `frontend/src/App.jsx` | 大厅、构筑、游戏、战斗、分支和异步生命周期主编排 | `api.js`、`dndLabels.js`、`components/*`、action options、CSS、build/lint |
| `frontend/src/dndLabels.js` | D&D 2024 中文化字典、默认构筑状态及纯格式化/映射工具函数 | `App.jsx`、`components/*`、`dndLabels.test.mjs` |
| `frontend/src/components/` | `SessionPanels.jsx`、`CharacterSheetDetail.jsx`、`ShopCarousel.jsx`、`MarkdownBlock.jsx`、`Icons.jsx` | `App.jsx`、`DescriptionTooltip.jsx`、`index.css` |
| `frontend/src/LevelBuildChoices.jsx` | 建卡等级相关的子职业、属性提升、专精和特性预览；规则值来自服务端 | `App.jsx` 构筑指纹与迟到响应守卫、creation-options API |
| `frontend/src/DescriptionTooltip.jsx` | 全局单窗说明：悬停1.5秒固定、光标进度圈、叉号/Escape关闭，Portal避免裁切 | `App.jsx`、action options 与 builder 装备目录的 description/notes、法术施法资料、视口与键盘验收；不回写角色状态 |
| `frontend/src/descriptionTooltipState.js`、`frontend/src/descriptionMarkdown.js` | 单窗所有权与计时状态机；只整理显示层阶梯列表/强调格式 | 延迟回调隔离、固定后手动关闭、保留真正嵌套/代码和原文字词 |
| `frontend/src/retryUi.js` | 主持回复重试与玩家消息重写的可恢复 UI 回滚纯状态转换 | `App.jsx`、`retryUi.test.mjs`、消息索引语义 |
| `frontend/src/narrativeRollUi.js` | 主持叙事内公开骰点/战斗标记的语义分类，以及玩家时间线暗骰过滤 | `App.jsx`、Markdown 前缀契约、`narrativeRollUi.test.mjs` |
| `frontend/src/rollUi.js` | 骰点按 id 合并及结算状态展示；明暗骰由回复上方折叠框承载 | `App.jsx`、RollRecord、SSE、`rollUi.test.mjs` |
| `frontend/src/index.css` | 当前主要视觉与响应式样式 | App class names、浏览器检查 |

这不是完整文件列表。新增公共模块、移动职责或改变边界时更新本表；局部 helper 不需要记录。

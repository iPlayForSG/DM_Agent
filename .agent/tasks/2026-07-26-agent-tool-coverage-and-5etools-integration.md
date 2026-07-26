# Agent 工具覆盖补齐与 5e Tools 能力接入

Status: active
Updated: 2026-07-26

## Goal

1. 让项目文档与工作树事实一致。
2. 补齐多 Agent 编排：把后端**已实现但没有任何 Agent 能调用**的能力做成注册工具，交给应当拥有它的子 Agent；验证通过后推送。
3. 从 `E:\5e Tools` 抽取实用的 DM 工具能力（遭遇难度、CR 估算、战利品、角色创建选项数据），实现为本地确定性工具并完成注册。

## User-visible outcome

Setup Agent 能真正完成建卡与选冒险；Combat Agent 能移除战斗员并评估遭遇难度与自定义怪物 CR；Downtime Agent 能产出符合规则的战利品；Level Up Agent 能校验角色卡。文档不再出现过期数字与已废弃断言。

## Scope / Non-goals

- In scope：新增工具 schema + service 实现 + guardrail + `AGENT_SPECS` 归属 + phase allowlist + 测试 + 文档同步 + 推送。
- Non-goal：不引入 5e Tools 的前端 UI/渲染栈；不整体 vendored 其 JSON 语料；不改动既有回合事务边界。

## 事实基线（2026-07-26 已验证）

- 后端测试须用 `C:\Users\iPlayForSG\.conda\envs\DM_Agent\python.exe`；默认 `python`（D:\Anaconda3）缺 fastapi/langgraph。
- 基线 `python -m unittest discover -s tests`：**114 tests OK**。
- `LANGGRAPH_TOOL_SCHEMAS` 共 **30** 个 schema，全部至少属于一个 Agent；phase allowlist 与 Agent ownership 的交集无“阶段允许但 Agent 无法执行”的空洞。
- 父图编排已是真实 LangGraph：`prepare_turn → input_gate → director → route_phase → rules → memory_context → (5 选 1 Specialist 子图) → auditor →(修复回路/audit_failed/narrator)→ finalize_turn`。
- 远端 `origin` = https://github.com/iPlayForSG/DM_Agent.git，分支 main，与 origin/main 同步，工作树有 20+ 未提交修改。

## 已识别缺口：后端已有但无 Agent 可达的能力

| 后端能力 | 现有入口 | 应属 Agent |
|---|---|---|
| `RuleCatalog.get_builder_catalog` | REST `/rules/character-builder` | setup |
| `Library.get_all_classes` / `get_spells_by_class` / `get_spell_details` | REST `/library/*` | setup |
| `starter_shop.get_shop_catalog` + `RuleCatalog.get_starter_options` | 仅建卡内部 | setup |
| 角色落地（`apply_builder_defaults` + `validate_character` + 写入 GameState） | REST `POST /characters` + `POST /games` | setup |
| `adventure_service.generate_initial_adventures` / 选定 hook | REST `/select-adventure` | setup |
| `RuleCatalog.validate_character` | 仅建卡内部 | setup / level_up |
| `GameLogic.remove_combatant` | REST `/encounters/remove-combatant` | combat |

## 5e Tools 抽取候选

- `js/encounterbuilder/` + `data/encounters.json`：遭遇 XP 预算与难度分级。
- `js/crcalculator.js`：自定义怪物 CR 估算（防御/攻击 CR 折中）。
- `js/lootgen/`：宝藏与魔法物品表。
- `data/races.json`、`data/backgrounds.json`、`data/feats.json`、`data/class/`：角色创建选项。

## Progress

- [x] 建立事实基线与缺口矩阵。
- [x] Phase A（首轮）：刷新 `NEXT_SESSION_HANDOFF.md`，修正 `common-pitfalls.md` 的过期断言与解释器坑点。
- [x] Phase B：新增 7 个工具并完成 schema/guardrail/ownership/phase 四处注册。
- [x] Phase C：5e Tools 能力抽取与注册。
- [x] Phase D：全量验证、文档终稿、推送。

### Phase B 交付

新增工具与归属：

| 工具 | 归属 Agent | 副作用 |
|---|---|---|
| `list_character_options` | setup, level_up | read |
| `list_class_spells` | setup, level_up | read |
| `list_starter_equipment` | setup | read |
| `validate_character_sheet` | setup, level_up | read |
| `create_party_character` | setup | state_write，需确认 |
| `select_adventure_hook` | setup | campaign_write，需确认 |
| `remove_combatant` | combat | combat_write，需确认，需活跃遭遇 |

- `create_party_character` 复用 `apply_builder_defaults` + `validate_character`：校验失败直接拒绝，不落地半成品角色。
- `select_adventure_hook` 只改 `GameState`，不写存档、不追加聊天记录——提交仍由 `finalize_turn` 负责。
- `test_agent_factory` 的硬编码工具清单改为从 `LANGGRAPH_TOOL_SCHEMAS` 派生，消除同类漂移。
- 新增 `tests/test_setup_agent_tools.py`（19 项），覆盖成功路径、拒绝路径与四处注册一致性。

### Phase C 交付

- 新增 `backend/encounter_math.py`：移植 5e.tools 的 2024 XP 预算表、`data/msbcr.json` 与 `crcalculator.js` 的双面 CR 折中。只移植数值与推导逻辑，不引入 UI/渲染/正文。
- 新增工具 `estimate_encounter_difficulty`、`estimate_monster_cr`，只读、无 state patch，归属 exploration / combat / downtime。
- 即兴敌人（无模板）按防御面估算 CR，并用 `cr_source` 区分 `template` 与 `estimated_from_defense`。
- 新增 `backend/utils/import_5etools_builder_options.py`：幂等增量导入 XPHB 建卡选项。已执行：物种 4→10、背景 7→16、起源专长 10→13；既有条目未被改写。
- 新增 `tests/test_encounter_math.py`（26 项），含 CR 折算与 JS `Math.round` 语义的逐值对齐测试。

## Decisions

- 2026-07-26：多 Agent 重构的真实缺口不是图结构，而是**工具面覆盖**；父图与子图隔离已达标，不重写编排骨架。
- 2026-07-26：5e Tools 的接入方式是"移植算法与数值表 + 增量导入建卡数据"，不 vendored 其前端栈，也不整体复制 JSON 语料。
- 2026-07-26：遭遇难度/CR 工具定位为 DM 判断依据，保持只读；不让它们影响回合事务或写入权威状态。
- 2026-07-26：`_decimal_to_cr` 必须显式实现 JS 的 `Math.round`（`floor(x+0.5)`），Python 的银行家舍入在 0.625 等取值上会分歧。

## Validation

2026-07-26 实测：

- 后端 `unittest`：114（基线）→ 133（Phase B）→ **159（Phase C）**，全部通过。
- 前端 `npm run build` 成功；`npm run lint` 0 errors、2 条既有 Hook dependency warning。
- `git diff --check` 干净；`backend/.env` 未被跟踪。
- 工具矩阵闭合：39 个 schema 全部有归属，无 phase/ownership 空洞。
- 建卡导入脚本重跑为 0 新增，幂等性成立。

**未验证**（单元测试不能替代）：真实 provider smoke、浏览器连续回合回归、本地 GGUF embedding server 启动。

## Remaining work

- 用有效模型档案完成真实 Director → Specialist → Auditor → Narrator 链路 smoke。
- 浏览器连续回合玩家回归，重点看 Setup Agent 现在能否用新工具走完建卡到选冒险。
- 复核前端怪物编辑 UI 与只读标准怪物 API 的产品边界（`POST /api/v1/monsters` 固定 405）。
- 可选：把 `ability_options`（2024 背景的属性加值可选项）接入前端建卡 UI；当前只作为附加字段存在，未被消费。

## Resume instructions

用 `C:\Users\iPlayForSG\.conda\envs\DM_Agent\python.exe -m unittest discover -s tests` 复核；新增工具必须同步 schema、service、guardrail、`AGENT_SPECS`、phase allowlist 与测试。

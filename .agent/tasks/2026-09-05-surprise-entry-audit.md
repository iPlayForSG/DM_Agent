# 突袭进战规则核对

Status: completed
Updated: 2026-09-05

> 下述 Findings 为实现前的审计结果，相关缺口已由 [突袭规则实现](2026-09-05-surprise-combat-rules.md) 补齐；后续任务以当前代码与该实现计划为准。

## Goal

核对本地 2024 规则书与后端的躲藏、突袭和进战流程，判断玩家所述行动应有哪些裁定；本任务仅审计，不改规则或重算存档。

## Progress

- [x] 找到本地玩家手册 2024 的躲藏动作、隐形状态、突袭及不可见攻击规则，并核对官方 Basic Rules。
- [x] 检查敌对意图、start_encounter、roll_initiative、技能检定、攻击骰及状态模型。
- [x] 通过不保存的合成状态验证缺少状态联动，并整理审计结论。

## Decisions

- 仅依据用户已提供的游戏片段，不读取完整会话或真实玩家存档；无法据此断言敌人是否已经警觉。
- 以本地核心规则/玩家手册2024 为规则来源，避免目录内旧模组/旧扩展中的突袭描述混入核心裁定。

## Findings

- 2024 躲藏是有环境/视野前提的 DC15 敏捷（隐匿）检定；成功后获得躲藏来源的隐形，并记录检定总值供察觉发现。
- 突袭发生于战斗开始：未察觉危险者先攻劣势；隐形者先攻优势。对看不见自己的目标攻击有优势，躲藏会在攻击等触发条件后结束。
- 现有“突袭/偷袭”测试只验证 hostile_attack 意图与进战/攻击工具路由，不代表上述规则完整实现。
- start_encounter 默认立即自动投先攻；roll_initiative 固定普通 1d20+加值，没有 roll_mode 或突袭判定参数。
- 通用隐匿检定只结算数值，不负责躲藏的环境前提、发现 DC、来源状态与失效；攻击虽支持显式 roll_mode，但不会自动从躲藏/隐形推导优势。
- 同一场已开始的战斗不能因再次声明偷袭就重投先攻或重新应用开战突袭；普通伏击也不授予游荡者 Sneak Attack 职业伤害。

## Evidence

- [本地 2024 躲藏动作](../../backend/Documents/DND5e%202024/核心规则/玩家手册2024/术语汇编/动作.md)：DC15、环境前提、发现 DC 与失效条件。
- [本地 2024 战斗流程](../../backend/Documents/DND5e%202024/核心规则/玩家手册2024/进行游戏/战斗流程.md)：突袭先攻劣势。
- [本地 2024 隐形状态](../../backend/Documents/DND5e%202024/核心规则/玩家手册2024/术语汇编/状态.md)：先攻优势和攻击影响。
- [官方 Basic Rules](https://www.dndbeyond.com/sources/dnd/br-2024/playing-the-game)：与本地突袭及不可见攻击裁定一致。
- `backend/agent_tools.py:start_encounter`、`backend/game_logic.py:roll_initiative/roll_skill_check/resolve_attack`、`tests/test_dm_graph_workflow.py:test_surprise_attack_terms_route_to_encounter_and_attack_tools`。

## Validation

- [x] 不保存的合成 GameState：隐匿检定成功，状态列表仍为空；给双方通用状态列表分别设置 invisible/surprised 后，先攻合计只掷 2 个 d20，均为 normal；隐形者默认攻击只掷 1 个 d20，仍为 normal。
- [x] 核对原始本地规则与规范化 grep_corpus 中均存在相关 2024 条文；未读取玩家存档或完整会话，未调用真实模型或修改产品代码。

## Remaining work

- 本次审计已完成，后续规则实现与验证见上述链接。

## Resume instructions

后续若实现，需覆盖环境前提、观察者察觉、躲藏来源状态、带优劣势的先攻与攻击/施法后的状态失效；不得把玩家文字直接视为突袭成功。

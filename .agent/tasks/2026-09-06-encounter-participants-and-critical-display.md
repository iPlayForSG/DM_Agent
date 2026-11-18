# 多敌人入战与重击反馈

Status: completed
Updated: 2026-09-06

## Goal

取消单人1级按敌人数拒绝入战的限制，以非阻断难度提醒替代；骰点记录与攻击摘要明确标注重击。

## User-visible outcome

现场参与战斗的多个敌人可共同进入先攻；攻击自然20显示“自然20 · 重击”，伤害记录显示实际重击骰式。

## Scope / Non-goals

- In scope: 入战人数限制与DM参与者提示、重击事件/schema、Agent/本地攻击摘要、前端骰点兼容与回归。
- Non-goal: 改写历史战斗状态、重掷旧回合、将普通技能自然20判成自动成功，或改为2014版突袭规则。
- 其他既有即兴敌人强度保护不在本次人数限制修复范围。

## Relevant context and files

- `backend/rules_catalog.py`、`backend/agent_tools.py`：非阻断人数提醒及入战反馈。
- `backend/game_logic.py`：独立参战实例ID、重击结算及自然骰/重击观察元数据。
- `backend/models.py`、`frontend/src/rollUi.js`、`frontend/src/App.jsx`：骰点记录与呈现。
- `backend/action_service.py`、`backend/combat_feedback.py`：本地与Agent攻击入口共用结果文案。

## Progress

- [x] 核对规则与当前实现，确认2024突袭不跳过首回合。
- [x] 调整人数策略与重击反馈，补修中文/长名称敌人实例ID覆盖。
- [x] 完整回归与合成浏览器验收。
- [x] 核对基线后同步、更新相关长期记忆。

## Decisions

- 2026-09-06：参与者由场景事实决定，不因单人低等级而删去敌人。人数劣势仅提供内部难度提醒。
- 2026-09-06：新记录明确保存natural/critical；旧攻击记录只用实际保留的d20兼容显示，不按总值推断自然20。
- 2026-09-06：保留已有重击结算，骰子翻倍而固定加值不翻倍；显示更改不得重复计算伤害。

## Discoveries / surprises

- 移除人数限制后的回归发现第二个丢失原因：start_encounter将遭遇ID与中文名字交给ASCII slug，导致不同中文敌人ID相同；长名称也可能因截断碰撞。新入战与add_enemy改用独立实例ID，不迁移已保存ID。
- 失败工具不进入成功tool_results，其拒绝原因记录在node_traces；不能只看成功结果判断DM是否尝试过多敌人入战。

## Validation

- 完整后端412项：411通过、1项真实CLI opt-in跳过。
- 前端build通过，lint 0 errors、2条已有Hook warning；17项Node回归通过。
- 回归覆盖多人先攻、突袭不跳回合、中文及长名称ID、增援实例、武器/法术及Agent/本地入口重击、SSE元数据、持久化和普通检定自然20。
- Chrome合成场景验证两名地精共同显示，攻击自然20与重击伤害及摘要实际骰式可见。
- 未重放真实玩家行动；真实模型是否始终按场景选择全部参战者未验证。
- 11个源文件按基线核对后同步，保留之前修改；源码与测试副本一致。
- 实际后端已完成重载，OpenAPI包含natural/critical字段；没有重写现有战斗或重掷历史骰点。
- 相关路径、Markdown链接及git diff --check通过；临时验收页面和服务已关闭。

## Remaining work

- 无。后续真实模型在不同场景的参战者选择仍需持续观察，不能把合成验收等同于所有叙事场景均已验证。

## Resume instructions

1. 保留之前等级建卡与套组说明的未提交修改。
2. 隔离副本为`output/combat-control-fix`，本任务基线为`output/critical-display-baseline`。
3. 不操作真实存档或重放玩家行动。

# 玩家回归与权威法术豁免

Status: active
Updated: 2026-07-26

> 2026-08-28 架构校准：实时运行时已由 [ADR-0003](../../docs/adr/0003-single-dm-brain.md) 收敛为单一 DM Brain。下文 Auditor/Narrator 内容只描述历史修复；后续回归以确定性 validator、`finalize_turn` 和 interrupt 事务边界为准。

## Goal

完成当前未提交的敌方回合、行动建议和属性生成改动回归，并修复法术豁免目标与 DC 仍由非权威输入驱动的问题。

## User-visible outcome

玩家可稳定连续游玩；敌方回合不会被叙事跳过或显示玩家建议；角色构筑支持三种属性方式；法术豁免只对有效目标并使用权威 DC 结算。

## Scope / Non-goals

- In scope：当前 dirty set、真实模型/浏览器回归、saving target/DC authority、相关文档和测试。
- Non-goal：本计划不自动授权提交/push，也不包含后续完整遭遇难度计算器。

## Relevant context and files

- `NEXT_SESSION_HANDOFF.md`：原始回归断点，但其状态数字已经过期。
- `backend/agents/game_master.py`、`backend/dm_graph.py`：敌方回合校验/修复。
- `backend/agents/suggestions.py`、`frontend/src/App.jsx`：建议权利与当前行动者 UI。
- `backend/ability_scores.py`、`backend/rules_catalog.py`：属性生成与验证。
- `backend/agent_tools.py`、`backend/action_service.py`、`backend/tool_registry.py`：豁免结算入口。

## Progress

- [x] 敌方回合无工具回复进入 audit/repair。
- [x] 敌方当前行动者时隐藏玩家 action suggestions。
- [x] 接入购点、标准数组、4d6 去最低及记录验证。
- [x] 法术豁免拒绝缺失目标/来源，并从角色与法术资料权威推导 DC/豁免属性。
- [x] Auditor 修复后再次拒绝会失败并回滚，不再按重试次数放行 Narrator。
- [x] 当前后端 114 tests、前端 build、lint（2 warnings）通过。
- [ ] 使用有效模型完成连续玩家回归。
- [ ] 复核怪物编辑 UI 与标准怪物只读 API 的产品边界。

## Decisions

- 2026-07-20：DM-controlled combatant 必须通过工具结算/放弃并推进，不能只接受叙事文本。
- 2026-07-20：行动建议只在玩家拥有当前决定权时展示。
- 2026-07-26：Auditor 只有明确接受才可进入 Narrator；第二次拒绝走失败回滚。
- 2026-07-26：角色法术豁免忽略调用方 DC，以职业施法属性和法术说明为权威。

## Discoveries / surprises

- 前端标准怪物保存调用与后端固定 405 冲突，需要单独确定产品行为。

## Validation

- [x] `python -m unittest discover -s tests -v` — 114 tests passed（2026-07-26）。
- [x] `npm run build` — passed（2026-07-26）。
- [x] `npm run lint` — 0 errors, 2 warnings（2026-07-26）。
- [ ] 有效 provider smoke。
- [ ] 约 20 回合浏览器回归，覆盖探索、NPC、检定、法术、战斗、删除/重写和回复长度。

## Remaining work

- 完成真实模型和浏览器回归后再决定是否提交/push。

## Resume instructions

1. 运行 `git status --short`，保留现有 dirty set。
2. 读 `common-pitfalls.md` 的“规则与 schema 联动”。
3. 从有效 provider smoke 与浏览器玩家回归开始；优先处理玩家可见契约问题。

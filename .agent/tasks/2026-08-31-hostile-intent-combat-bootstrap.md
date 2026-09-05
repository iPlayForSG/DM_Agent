# 敌对意图识别与同回合战斗启动

Status: completed
Updated: 2026-08-31

## Goal

修复探索阶段明确敌对行动被当作普通对话的问题：扩充确定性词表，词表未命中时由受约束的模型分类补充 `TurnIntent`，并允许建立遭遇后在同一玩家回合刷新战斗能力完成结算。

## User-visible outcome

“突袭我面前的地精”等明确攻击会进入权威战斗流程，而不是只重复描写机会；未覆盖的新表达可由 Agent 意图分类兜底。明确攻击若没有相应工具结算，不得以纯叙事成功提交。

## Scope / Non-goals

- In scope：`backend/dm_graph.py` 的意图规划、DM 私有工具循环动态能力、确定性校验、回复长度时机及对应测试。
- Non-goal：不修改玩家存档，不把模型分类结果直接当作游戏事实，不绕过工具 guardrail、当前行动者或 `finalize_turn` 事务边界。

## Relevant context and files

- `backend/dm_graph.py`：词表规划、profile 工具裁剪、校验与最终回复长度处理。
- `backend/agents/game_master.py`：DM 私有模型/工具循环与阶段能力刷新。
- `backend/agents/specs.py`：探索和战斗能力边界。
- `tests/test_dm_graph_workflow.py`、`tests/test_dm_loop_acceptance.py`：意图、工具范围、修复与端到端回归。

## Progress

- [x] 从游戏 `111` 的权威 trace 定位误分类、工具裁剪和长度扩写链路。
- [x] 实现词表与受约束 Agent 意图兜底。
- [x] 实现遭遇建立后的同回合战斗能力刷新。
- [x] 实现明确攻击零工具叙事拒绝和结算后长度处理。
- [x] 完成目标测试、完整后端测试和差异检查。

## Decisions

- 2026-08-31：确定性词表仍是快速路径；只有没有行动/规则/显式工具信号的输入才调用模型意图兜底，模型只能从有限 turn type 和工具名中选择。
- 2026-08-31：模型分类只影响能力建议，不直接写 `GameState`；所有战斗事实仍须由真实工具产生。
- 2026-08-31：`hostile_attack` 专指武器、徒手、射击等直接攻击；纯施法使用独立标签，避免强制错误的 `attack_target` 后续。
- 2026-08-31：探索阶段仍只在第一步暴露 `start_encounter`；成功建立遭遇后由确定性校验按新 combat phase 刷新工具面，而不是预先越过阶段边界。

## Discoveries / surprises

- 当前 `conversation` profile 会把探索阶段本来拥有的 `start_encounter` 裁掉。
- 当前探索阶段只暴露 `start_encounter`，而 DM 私有循环不会在该工具成功后刷新父图的 phase/allowed tools，因此无法同回合继续攻击。
- 游戏 `111` 设置了 1000–2000 字回复；57 字未结算叙事被长度编辑器扩写两次至 1314 个可见字符。
- 沙箱会阻止 Codex CLI 与 SQLite 测试写系统临时目录；真实 CLI 冒烟和完整测试需在沙箱外运行，不能把该权限错误当作分类失败。

## Validation

- [x] `tests.test_dm_graph_workflow` 与 `tests.test_dm_loop_acceptance` — 目标行为通过；沙箱内仅 SQLite tempfile 权限用例失败，沙箱外完整套件覆盖该用例。
- [x] `python -m unittest discover -s tests -v` — 沙箱外 222 项全部通过。
- [x] `python -m compileall -q backend` — 通过。
- [x] Codex CLI `gpt-5.6-terra/high` 合成意图冒烟 — 未收录措辞返回 `action_resolution`、`agent_fallback`、`hostile_attack` 与 `start_encounter`/`attack_target`。
- [x] `git diff --check` — 通过，仅有仓库既有的 LF/CRLF 工作树提示。

## Remaining work

- 无。

## Resume instructions

任务已完成。后续扩展意图标签时必须保持有限枚举与工具白名单，并为“模型分类结果不能直接成为世界事实”保留回归测试。

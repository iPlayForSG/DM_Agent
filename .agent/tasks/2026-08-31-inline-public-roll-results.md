# 叙事内公开骰点与战斗结算强调

Status: completed
Updated: 2026-08-31

## Goal

让主持叙事在动作发生的位置展示非暗骰的权威结果，并用不同语义样式突出普通骰点与攻击结算，同时保证暗骰不进入玩家叙事或时间线。

## User-visible outcome

普通公开检定在相关句段旁显示为彩色斜体；攻击结算在攻击描写旁显示为彩色粗体。结果来自成功工具而不是模型编造，且不会统一堆在回复开头。

## Scope / Non-goals

- In scope：主持提示格式、通用骰子的公开/隐藏标记、最终正文兜底定位、Markdown 渲染语义、玩家时间线过滤和相关测试。
- Non-goal：不改变骰子算法、AC/DC、命中与伤害规则，不把暗骰内容公开给玩家。

## Relevant context and files

- `backend/prompts.py`：规定 Agent 如何在相关叙事位置输出公开结算标记。
- `backend/dm_graph.py`：提交前用成功工具结果补齐遗漏的公开标记。
- `backend/agent_tools.py`：通用骰子区分 `public` 与 `hidden`。
- `frontend/src/App.jsx`、`frontend/src/narrativeRollUi.js`、`frontend/src/index.css`：渲染和样式。

## Progress

- [x] 建立公开骰点格式与暗骰边界。
- [x] 实现后端叙事标记兜底和测试。
- [x] 实现前端语义渲染、时间线过滤和测试。
- [x] 完成后端、前端与差异验证。

## Decisions

- 2026-08-31：使用 Markdown 原生强调作为传输格式：`*骰点｜…*` 与 `**战斗｜…**`；前端只给这两个前缀附加语义 class，不改变普通强调文本。
- 2026-08-31：模型负责把标记写在对应叙事句段旁，确定性提交层只在模型遗漏时按工具 payload 中的角色、目标、技能或原因定位补齐。
- 2026-08-31：用户明确要求公开骰点使用斜体，因此该单一语义是现有中文界面“禁用斜体”的局部例外。

## Discoveries / surprises

- 当前 `ToolResult` 已保留完整权威摘要，但 `ChatMessage` 只保存最终正文；若只改前端，无法把时间线结果可靠关联回对应回复段落。
- 暗骰即使被正文和时间线 UI 跳过，完成回合后派生的 SSE `tool.completed` 仍会进入主持思考面板；必须在服务端构造玩家事件时过滤，不能只靠 CSS 或前端隐藏。
- 同一回合可能出现摘要完全相同的多次骰点；正文标记必须按成功工具结果的次数逐个配对，不能用集合判定“出现过即可”。

## Validation

- [x] 项目 Conda 环境完整后端测试：226 tests，OK。
- [x] 直接运行 `narrativeRollUi.test.mjs` 与 `retryUi.test.mjs`：4 tests，OK（沙箱内 `node --test` 子进程因 EPERM 不可用）。
- [x] `npm run build`：成功；`npm run lint`：0 errors、2 个既有 Hook dependency warnings。
- [x] `git diff --check`：通过。
- [x] 浏览器检查实际应用加载后的生产 CSS：两类语义样式与无横向溢出符合设计；未运行真实模型带骰点回合的端到端截图。

## Remaining work

- 无。

## Resume instructions

本计划已完成；后续若调整标记格式，需同步检查提示词、提交层清洗、SSE 过滤、前端语义识别和测试。

# DM Agent Loop 重构

Status: active
Updated: 2026-08-28

## Goal

以“规则边界内高度自由的单一 DM”为核心，重新设计实时回合 Loop 与可选 Agent 协作方式，减少无信息增量的 Director/Auditor/Narrator 流水线，并保持权威状态、原子提交、interrupt 恢复和玩家决定权。

## User-visible outcome

玩家始终面对人格、叙事和上下文连续的 DM；DM 可以自由推进场景、扮演 NPC 和即兴创作，但机械结算与持久事实仍由确定性工具和权威状态约束。普通回合减少模型往返、延迟和审计式拒绝，复杂规则或长程规划才按需调用隔离的辅助 Agent。

## Scope / Non-goals

- In scope：实时 DM Loop、上下文装配、工具能力边界、事务/interrupt、最小在线校验、可选辅助 Agent 的调用条件与交接契约、回归评估方案。
- Non-goal：不削弱确定性规则层；不让模型直接 patch `GameState`；不把离线质量评估重新塞回每回合在线审计；首批迁移不新增尚无明确任务的辅助 Agent。

## Relevant context and files

- `backend/dm_graph.py`：当前父图、上下文装配、DM 模型步、确定性校验、事务与提交边界。
- `backend/agents/`：持续 DM 私有循环、阶段能力、工具适配与提交后 Suggestions 投影。
- `backend/agent_tools.py`、`backend/tool_registry.py`：确定性“手”和能力边界。
- `backend/models.py`：`GameState`、turn trace、pending turn 与未来 session event 契约。
- `backend/main.py`：turn/interrupt 结果持久化边界。
- `/Users/xianzongyou/Downloads/ai-agent-book-main/book/chapter10.md`：多 Agent 的新信息判据、上下文隔离与显式 handoff。
- Anthropic 2026 Managed Agents / containment 文章：session、harness、hands 解耦，以及以能力隔离替代高频行为监督。

## Progress

- [x] 从 `main` 创建 `refactor-agent_loop` 并确认基线工作树。
- [x] 复核当前父图、Specialist 子图、审计/叙事顺序、interrupt 与保存边界。
- [x] 阅读本地书中多 Agent 协作、上下文隔离、控制平面和失败模式章节。
- [x] 核对 Anthropic 2025–2026、OpenAI 官方 Agent 编排资料。
- [x] 形成“单一 DM Brain + 确定性规则内核 + 按需只读辅助 Agent”的目标方向。
- [x] 用户确认开始实现，首批迁移聚焦在线主 Loop 与 interrupt 原子性。
- [x] 父图收敛为一个持续 DM Brain；移除 Director、Rules Agent、阶段 Specialist、LLM Auditor 和独立 Narrator 运行链。
- [x] 角色身份与阶段能力拆分；DM 私有循环按 phase allowlist 二次收窄工具并串行执行写入。
- [x] 在线模型步移除证据启发式二次审判，只保留模型健康、工具预算和确定性修复边界。
- [x] interrupt 结果不再发布 staged state；checkpoint 丢失时回滚且不重放“确认”。
- [x] 行动选项正文清理改为非事务展示处理，不再回滚正确主回合。
- [x] 补充新架构、事务边界和无证据审计 characterization tests。
- [x] 创建 Accepted ADR，并同步架构文档和长期 memory。
- [x] 增加离线 Loop 验收基线：普通叙事 1 次模型调用、单工具回合 2 次调用、提交叙事跨回合可见、phase 工具隔离。
- [x] 为状态摘要、近期历史、长期记忆和 RAG 上下文设置独立预算，并在 trace 中记录长度与截断项。

## Decisions

- 2026-08-28：实时玩家交互采用一个持续身份的 DM Brain；阶段是上下文与能力提示，不再映射为互相接棒的 DM 人格。
- 2026-08-28：在线正确性依靠工具前置 guardrail、确定性状态不变量和原子提交，不保留常驻 LLM 事实 Auditor。
- 2026-08-28：辅助 Agent 只有在能引入独立新信息、隔离大量上下文或真正并行时才启动；默认只读，返回结构化 brief/artifact，不写权威状态。
- 2026-08-28：叙事自由分为短暂表现层、可持久剧情事实和机械事实三层；后两层分别通过受限语义事件工具和确定性规则工具落地。
- 2026-08-28：session event log、harness 和工具执行环境应解耦；pending interrupt 不得把 staged state 当作已提交存档。

## Discoveries / surprises

- 重构前 Director 的输出不决定实际路由；路由仍由 phase 强制决定。
- 重构前 Narrator 位于 Auditor 之后，最终改写没有再次经过事实检查。
- 重构前 `input_required` 结果会被 API 无条件保存；若 interrupt 前已有成功写工具，可能暴露未经过 `finalize_turn` 的 staged state。
- 当前目标测试在本机 `.venv` 可运行，但缺少被忽略的 `backend/data/spells.json`，导致 4 个法术数据相关失败。
- 原 `_call_model` 中约千行叙事证据启发式与重试已从代码删除；grounding/turn-claim helper 只保留为离线或独立测试能力，不进入实时 DM Loop。
- `GameLogic.get_recent_history()` 原先只限制消息条数，单条超长消息仍可无限放大提示词；现在上下文装配层保留最新历史并执行字符预算。

## Validation

- [x] `.venv/bin/python -m unittest tests.test_dm_graph_workflow tests.test_dm_agent_team -v` — 67 项中 63 项通过；4 项因本地缺少 ignored `spells.json` 失败。
- [x] `git diff --check` — 研究阶段变更前通过。
- [x] 新 Loop characterization tests：staged interrupt、checkpoint fallback、单一 DM 工具循环、无证据启发式重试、提交后建议隔离。
- [x] `python -m compileall -q backend` — 通过。
- [x] 非法术数据依赖的 81 项测试 — 全部通过。
- [x] 完整后端 162 项测试 — 149 项通过；13 项失败均由本地缺少 ignored `backend/data/spells.json` 引起，包含 4 项施法测试和 9 项建卡/法术目录级联测试。
- [x] `git diff --check` — 实现与文档变更后通过。
- [x] `tests.test_dm_loop_acceptance` 与既有 campaign-memory 定向测试 — 6 项全部通过。
- [x] 完整后端 167 项测试 — 154 项通过；13 项仍均由缺少 ignored `backend/data/spells.json` 引起，没有新增失败。
- [ ] 真实 provider 与连续玩家回归；本次未改前端或 API 契约，不要求前端 build/lint。

## Remaining work

### Stage 2：真实运行验收

- 使用真实 provider 做连续多回合人格、叙事连续性、工具调用、interrupt/resume 和延迟 smoke test。
- 记录普通对话、单工具回合和战斗回合的模型调用数与端到端耗时，确认相较旧流水线的实际收益。
- 恢复或生成本地 `backend/data/spells.json` 后重跑完整测试，消除环境性失败。

### Stage 3：DM 叙事自由与持久事实

- 用实际跑团样本检查“即时描写 / 可持久剧情事实 / 机械事实”的分层是否足够自然。
- 只有现有日志、线索、章节与场景工具无法表达明确用例时，才新增最小语义事件契约；模型仍不能直接 patch `GameState`。
- 增加长战役回归样本，验证上下文预算下当前场景、最新决定和未解决线索不会丢失。

### Stage 4：按需协作能力

- 从真实复杂任务中识别需要独立新信息、上下文隔离或并行计算的用例，例如规则调研、章节规划或大量素材整理。
- 针对首个明确用例定义只读 assistant 的最小 brief/artifact schema、超时/失败降级和引用方式；不预建常驻角色或恢复流水线接棒。
- 将辅助结果作为 DM 的可选上下文，不授予其权威状态写权限，也不增加每回合强制审计。

## Resume instructions

1. 读取本计划、`architecture-map.md` 与 `common-pitfalls.md`。
2. 不恢复已删除的控制 Agent 流水线；在线正确性继续放在确定性工具和事务边界。
3. 下一步从 Stage 2 的真实 provider smoke 开始；未配置时如实记录未验证，不用单元测试替代。

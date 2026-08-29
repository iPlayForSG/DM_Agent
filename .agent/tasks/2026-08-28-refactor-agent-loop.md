# DM Agent Loop 重构

Status: completed
Updated: 2026-08-30

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
- [x] 明确持久事实所有权：玩家输入只是行动、问题、回忆或假设；DM 主动记录已确认线索，不接受玩家用“记下来”创造世界事实。
- [x] 状态页增加“线索与证据”投影，展示 DM 已持久化的结构化 evidence。
- [x] 使用 Codex CLI `gpt-5.6-terra` medium 作为真实模型适配器，完成合成状态下的自然线索、连续探索、技能工具链与 interrupt/resume 黑盒测试。
- [x] 重构玩家确认边界：内部工具风险不再自动转化为玩家侧 interrupt，只有意图不明确且真正涉及玩家决定权的分叉才请求选择。
- [x] 使用原生 OpenAI-compatible provider 与本地浏览器完成合成玩家选择 interrupt/resume、缺失 checkpoint 回滚和界面视觉走查。
- [x] 使用原生 provider 完成普通对话、确定性章节写入和战斗收尾的统一模型调用数/核心 Loop 耗时矩阵。
- [x] 使用原生 provider 完成即时描写、可持久剧情事实、机械事实和长上下文回忆的四步 Stage 4 验收。
- [x] 复核按需协作边界：提交后的 Suggestion Agent 是当前唯一满足上下文隔离条件的明确辅助用例；没有预建第二个无真实任务的角色。

## Decisions

- 2026-08-28：实时玩家交互采用一个持续身份的 DM Brain；阶段是上下文与能力提示，不再映射为互相接棒的 DM 人格。
- 2026-08-28：在线正确性依靠工具前置 guardrail、确定性状态不变量和原子提交，不保留常驻 LLM 事实 Auditor。
- 2026-08-28：辅助 Agent 只有在能引入独立新信息、隔离大量上下文或真正并行时才启动；默认只读，返回结构化 brief/artifact，不写权威状态。
- 2026-08-28：叙事自由分为短暂表现层、可持久剧情事实和机械事实三层；后两层分别通过受限语义事件工具和确定性规则工具落地。
- 2026-08-28：session event log、harness 和工具执行环境应解耦；pending interrupt 不得把 staged state 当作已提交存档。
- 2026-08-28：`risk_level` 描述内部副作用、校验和回滚要求，不等于玩家侧确认策略。明确玩家指令已经构成授权；确定性结算和 DM 记账应静默执行；只有缺少明确意图的玩家命运或剧情分叉才用自然语言请求选择。
- 2026-08-29：以低风险编排工具 `request_player_choice` 作为唯一的新式玩家决策 interrupt；它必须在相关写工具之前调用，公开 payload 只包含自然问题和 2–4 个具体选项，不能暴露工具名、风险或持久化术语。
- 2026-08-29：旧版 `tool_confirmation` checkpoint 不继续重放，因为 LangGraph 恢复会从节点开头重启且旧语义已失效；恢复请求返回安全失败并发布初始快照，前端提供“清理并返回”入口。
- 2026-08-30：已由权威上下文建立的命名线索在“交给/接过/收好”等取得动作中应立即用 `record_evidence` 落库；意图层只提供窄范围工具建议，不能把玩家措辞提升为事实源。
- 2026-08-30：首个明确只读辅助用例沿用提交后 Suggestion Agent：输入已提交状态与叙事，输出三个 `ActionSuggestion`，45 秒模型超时，非法结果走确定性 fallback 或空列表；不进入主事务。未发现需要新增章节规划/规则研究 Agent 的真实用例。

## Discoveries / surprises

- 重构前 Director 的输出不决定实际路由；路由仍由 phase 强制决定。
- 重构前 Narrator 位于 Auditor 之后，最终改写没有再次经过事实检查。
- 重构前 `input_required` 结果会被 API 无条件保存；若 interrupt 前已有成功写工具，可能暴露未经过 `finalize_turn` 的 staged state。
- 当前目标测试在本机 `.venv` 可运行，但缺少被忽略的 `backend/data/spells.json`，导致 4 个法术数据相关失败。
- 原 `_call_model` 中约千行叙事证据启发式与重试已从代码删除；grounding/turn-claim helper 只保留为离线或独立测试能力，不进入实时 DM Loop。
- `GameLogic.get_recent_history()` 原先只限制消息条数，单条超长消息仍可无限放大提示词；现在上下文装配层保留最新历史并执行字符预算。
- “让玩家要求记住线索”不是有效验收：它既暴露系统记账术语，也允许玩家把未经 DM 确认的说法注入权威事实。真实验收必须从自然行动开始，由 DM 判断何时调用 `record_evidence`。
- 真实模型把“贴门倾听、无声撬门”误分为普通对话后只口头要求检定；补充自然动作词与 action-resolution guidance 后，重跑会串行执行倾听和开锁两次技能检定。
- 原静态确认绑定覆盖六个权威写工具，把副作用风险错误地提升成玩家授权。现已解除绑定并保留 `risk_level=high`，明确选择、章节收尾、败北结算、移除离场单位与结束遭遇均可在同一回合完成。
- 只恢复 `GameState` 不足以保证失败回合隔离：旧失败路径仍会在图输出中泄露 staged `tool_results` 和 `state_delta`。`finalize_turn` 现同时清空这两类投影，取消玩家选择也走同一事务回滚。
- 从 LangGraph interrupt 恢复时节点会从开头重跑，因此 interrupt 前不能放不可重复副作用；`request_player_choice` 在暂停前只组装纯 payload，实际状态工具必须等待选择结果后再执行。
- 合并 `origin/main` 时发现两个 `0002` ADR；单一 DM Brain ADR 已顺延为 `0003`，相关索引、架构文档和任务引用已同步。
- 实际 SQLite checkpointer 对不存在的 thread 返回空状态，随后会表现为 `KeyError('game_state')`，不一定抛出带 `checkpoint` 字样的异常。恢复前现显式检查 checkpoint values，真实后端回归确认会安全清除 pending 并回滚。
- 原生 provider 首次面对重大分叉时只在普通正文中表示“由你决定”，没有产出结构化选项；把契约加强为“必须等待玩家决定时必须调用工具、不能只用正文询问”后，同一输入稳定返回 `player_choice`。
- 当前工作副本的原生 OpenAI-compatible provider 已配置并完成合成回归；未读取或输出凭据，测试只使用虚构状态与文本。
- 真实状态写入基准暴露两个重叠误判：单独的“说明”被当作规则问答，明示工具名却未作为行动信号；现已收窄规则词表，并让非 `lookup_rules` 的建议工具参与行动分类。
- `completed=false` 原先仍会因同一句中的“章节/完成记录后”触发章节完成修复，反向要求 `completed=true`；显式布尔参数现在优先于自然语言启发式。
- 战斗击倒最后敌人后，`encounter_end_condition` 会先留下 `repair_required` 审计记录，再由 `end_encounter` 确定性修复；成功回合保留这条历史 issue 属于预期，不代表最终提交失败。
- 战斗收尾后权威 phase 会切回 exploration，因此最终 trace profile 可与初始路由不同；延迟报告分别记录初始与最终 profile，比较时以初始路由为准。
- Stage 4 首轮真实样本中，普通闲聊、机械检定和长上下文回忆均通过，但模型没有把权威日志里的蓝蜡封片交接持久化；加强“命名线索取得”意图提示后复跑，`record_evidence` 成功执行且没有新增 schema。
- 长历史合成状态将 recent history 压到 6000 字符预算，DM 仍能从独立 state/campaign memory 块准确回忆“西侧回廊”“先救书记员”和“第三块石砖后的冷风”。
- Suggestions 已满足最小辅助契约、隔离执行、超时和失败降级；规则 RAG 与 campaign memory 是确定性服务，新增 Agent 不会带来独立信息增量，故 Stage 5 不扩运行时拓扑。

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
- [x] 自然线索真实模型回合（Codex CLI GPT-5.6-Terra medium）— 玩家只拾取查看场景中已存在的蓝蜡封片；DM 主动调用 `record_evidence`，2 个模型步骤后自然叙事，无旧控制 Agent trace。
- [x] 连续探索真实模型回归 — 自然对话、对照观察、倾听、开锁、谨慎侦察及章节 interrupt/resume 全部经过单一 DM；修复后潜入回合串行执行 2 次技能检定，确认恢复不再二次索要确认。
- [x] 前端 `npm run build` — 通过；`npm run lint` — 0 error，保留既有 2 条 Hook dependency warning。
- [x] 完整后端 169 项测试 — 156 项通过；13 项仍均由缺少 ignored `backend/data/spells.json` 引起，没有新增失败。
- [x] Stage 2 目标测试 `tests.test_dm_graph_workflow tests.test_setup_agent_tools tests.test_agent_factory tests.test_dm_agent_team` — 100 项全部通过。
- [x] 完整后端测试 — 192 项全部通过；当前工作副本已具备本地法术数据，先前 13 项环境性失败不再出现。
- [x] 前端 `npm run build` — 通过；`npm run lint` — 0 error，仍为既有 2 条 Hook dependency warning。
- [x] `python -m compileall -q backend` 与 `git diff --check` — 通过；后者仅报告 Git 的 LF/CRLF 工作区提示。
- [x] 浏览器合成玩家选择状态 — 桌面布局、自然问题、四个具体选项、“暂不决定”和自由输入占位均正常；实际 SQLite checkpoint 缺失时修复后会清除 pending 并展示安全回滚说明。
- [x] 原生 provider 合成 interrupt/resume — 加强契约后 9.48 秒返回 `player_choice`，不推进回合且不发布工具结果/差异；14.92 秒恢复完成，记录 `interaction.player_choice`、推进至回合 1 并清除 pending。
- [x] 所有走查产物均已清理：合成游戏 JSON、rewind、临时 Vite env/进程、临时后端，以及按精确 thread id 生成的 checkpoint rows；未触碰既有游戏和 23333 进程。
- [x] 原生 provider 核心 Loop 最终报告 `backend/runtime-logs/dm_loop_latency_eval_20260830_003959.json`：普通对话 1 次模型调用 / 7.437 秒，章节写入 2 次 / 3.114 秒，战斗攻击并结束遭遇 4 次 / 8.447 秒；三类回合均完成、状态检查通过、报告 issue 为 0。
- [x] 相对重构前 `6f514b4` 图结构可证明的最少调用数，三类样本分别由 4→1、5→2、6→4，减少 75%、60%、33.3%。比较只覆盖 `DMAgent.run_turn` 核心图（含 provider 与确定性工具），不含 HTTP 传输和提交后 UI suggestions 投影，也不伪造旧版未实测耗时。
- [x] Stage 3 最终完整后端测试 — 194 项全部通过；首次沙箱运行的 tempfile/SQLite 权限错误已在沙箱外用同一命令复跑排除。
- [x] Stage 3 最终 `python -m compileall -q backend`、前端 `npm run build`、`npm run lint` 与 `git diff --check` — 全部通过；lint 仍只有既有 2 条 Hook dependency warning，diff check 仅有 LF/CRLF 提示。
- [x] Stage 4 最终报告 `backend/runtime-logs/narrative_fact_eval_20260830_005406.json` — 四步 issue 为 0：即时描写 1 次模型调用 / 6.565 秒且持久状态不变；命名线索 2 次 / 9.471 秒并写入 `story.record_evidence`；机械结算 3 次 / 11.699 秒并执行 `check.skill` 后持久化新证据；长上下文回忆 1 次 / 4.994 秒且三个锚点全部命中。
- [x] Stage 4 确定性长历史测试确认 recent history 截断后，当前场景、最新决定和未解决线索仍存在于最终 DM instruction。
- [x] 最终完整后端测试 — 196 项全部通过；Stage 2–5 的新增意图、真实评估与长历史回归均包含在内。

## Remaining work

### Stage 2：沉浸式授权与玩家决定权（2026-08-29 完成）

- 六个静态确认工具已解除 `requires_confirmation`，内部高风险标记、phase allowlist、规则校验和事务边界保持不变。
- 新增语义化 `request_player_choice`：明确指令和确定性收尾不暂停，真正含糊的重大决定才给出具体选项；取消、恢复、checkpoint 丢失和 staged state 隔离已有回归覆盖。
- 前端显示“轮到你选择”的自然选项卡；旧 `tool_confirmation` 暂停可安全清理。存档、角色等产品级删除确认仍保留在原独立 UI。
- 代码、目标测试、完整后端测试、前端 build/lint、浏览器视觉走查与原生 provider interrupt/resume 均已通过。

### Stage 3：真实运行验收

- [x] 使用原生真实 provider 验证叙事响应、玩家选择工具、interrupt/resume、原子提交和端到端耗时。
- [x] 使用 OpenAI-compatible 原生传输复跑自然玩家输入；不再用 Codex CLI 独立进程耗时代替产品基线。
- [x] 补齐普通对话、确定性状态写工具与战斗回合的统一模型调用数/核心 Loop 耗时表，并与旧流水线可证明的最少调用数比较；最终采样见 Validation。
- [x] 当前本地法术数据可用，完整后端 192 项已通过，先前环境性失败已消除。

### Stage 4：DM 叙事自由与持久事实（2026-08-30 完成）

- 四步原生 provider 样本已覆盖即时描写、命名线索持久化、机械检定与长上下文回忆；最终 issue 为 0。
- 现有 `record_evidence` 与 `roll_skill_check` 足以表达本轮明确用例，仅加强工具描述、prompt 和自然取得意图，不新增 schema，模型仍不能直接 patch `GameState`。
- 长历史确定性测试和真实回忆回合均确认当前场景、最新决定、未解决线索不被 recent history 截断挤掉。

### Stage 5：按需协作能力（2026-08-30 完成）

- 当前唯一明确用例是提交后的 UI suggestions 投影，它隔离独立生成上下文且失败不应影响主事务；现有 Suggestion Agent 已满足。
- 最小 artifact 为三个 `ActionSuggestion(label, action)`；输入只读已提交状态/叙事/玩家输入，模型上限 45 秒，非法输出走确定性 fallback 或空列表。
- Suggestions 通过独立 API 在提交后运行，不拥有 `GameState` 写工具；规则检索和 campaign memory 保持确定性服务。未发现第二个有独立信息增量的真实任务，因此不新增常驻 Agent。

## Resume instructions

1. 读取本计划、`architecture-map.md` 与 `common-pitfalls.md`。
2. 不恢复已删除的控制 Agent 流水线；在线正确性继续放在确定性工具和事务边界。
3. Stage 2–5 均已完成；后续若出现需要独立新信息、隔离大量上下文或真并行的具体任务，再以只读 artifact 方式扩展，不预建角色。
4. 真实回归继续使用纯合成状态与内存 checkpoint；不要读取或复用玩家私有存档内容，也不要在报告保存完整 transcript。

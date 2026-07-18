# DM_Agent 多 Agent 架构设计

## 1. 结论

采用 LangGraph Custom Workflow 作为父图，每个业务节点挂载一个独立编译的 Agent 子图。每个 Agent 拥有独立的系统提示词、输入上下文、模型实例配置、工具白名单和内部 `model -> tools -> model` 循环。

确定性准备、提交和持久化步骤仍是普通节点，不伪装成 Agent。`GameState` 继续作为唯一事实源，任何业务状态变更只能由 Specialist Agent 的受控工具产生。

当前父图已经使用独立编译的 Rules 与 Specialist 子图；Director、Auditor 和 Narrator 使用独立 `create_agent` 图。旧 `DMAgentNode(handler=runner_method)` 包装层已经删除。

## 2. 父图

```text
START
  -> prepare_turn                 # deterministic
  -> director_agent              # structured route decision
       -> rules_agent             # rules question / rule context
       -> exploration_agent       # exploration, social, investigation
       -> combat_agent            # encounter and initiative turns
       -> downtime_agent          # inventory, recovery, progression
  -> state_auditor_agent          # structured verdict, no state mutation
       -> selected specialist     # repair loop, bounded
       -> narrator_agent          # accepted state
  -> commit_turn                  # deterministic atomic persistence
  -> suggestion_agent             # optional projection after commit
  -> END
```

`director_agent` 使用结构化输出决定唯一主 Specialist。规则资料可在 Specialist 之前按需调用 `rules_agent`；不要让多个可写 Agent 并行修改同一份 `GameState`。

## 3. Agent 契约

### Director Agent

- 输入：玩家原文、当前 phase/scene、遭遇摘要、pending input。
- 输出：`route`、`objective`、`requires_rules`、`risk_level`、`reason`。
- Tools：无。
- 禁止：叙事、掷骰、修改状态。

### Rules Agent

- 输入：标准化规则问题、角色/法术/怪物相关最小上下文。
- Tools：`lookup_rules`。
- 输出：带来源片段的 `RuleBrief`，供 Specialist 使用。
- 持久化：per-invocation，不保留独立对话记忆。

### Exploration Agent

- 输入：场景、最近对话、Campaign Memory、可见角色信息、可选 RuleBrief。
- Tools：`roll_skill_check`、`roll_saving_throw`、`cast_spell`、`use_item`、`use_feature`、`record_evidence`、`record_search_outcome`、`append_adventure_log`、`set_scene`、`start_encounter`。
- 输出：结构化事实摘要、工具结果、叙事草稿。
- 禁止：直接操作先攻、敌方 HP 或结束遭遇。

### Combat Agent

- 输入：完整 EncounterState、当前行动者、战斗角色卡镜像、可选 RuleBrief。
- Tools：`attack_target`、`cast_spell`、`use_item`、`use_feature`、`roll_saving_throw`、`adjust_hp`、`add_status`、`remove_status`、`set_initiative`、`roll_initiative`、`advance_turn`、`end_encounter`、`set_defeat_state`、受限的怪物生成工具。
- 输出：本行动者的结算结果和叙事草稿。
- 约束：一次只结算当前行动者；每次推进必须有工具结果；修复循环设硬上限。

### Downtime Agent

- 输入：队伍资源、库存、章节进度和当前地点。
- Tools：`add_inventory_item`、`use_item`、`record_major_experience`、`record_chapter_progress`、`append_adventure_log`、`set_scene`、`set_active_character`。
- 输出：结算结果和叙事草稿。
- 高风险章节变更继续通过 `interrupt()` 获取确认。

### State Auditor Agent

- 输入：回合前后状态 diff、工具调用轨迹、Specialist 草稿、权威当前行动者。
- Tools：只读检查工具；不得拥有任何写工具。
- 结构化输出：`accepted`、`issues[]`、`repair_route`、`required_tools[]`。
- 作用：检查叙事与状态一致性，不自行修补状态。

### Narrator Agent

- 输入：已通过审计的事实、工具结果、玩家可见上下文和长度偏好。
- Tools：无。
- 输出：唯一玩家可见正文。
- 禁止：创造未落库事实、修改状态、输出行动选项。

### Suggestion Agent

- 在主回合提交后运行。
- Tools：无；结构化输出三条建议。
- 失败只返回空建议，不影响已提交回合。

## 4. 状态边界

父图使用 `DMWorkflowState`，只保留跨 Agent 共享字段：

```text
game_state_before
game_state
player_input
route_decision
rule_brief
specialist_result
audit_result
final_response
tool_events
validation_issues
pending_input
```

各子 Agent 使用自己的私有 State schema。父图通过 adapter 将最小必要上下文映射给子图，再把结构化结果合并回来。禁止把完整聊天历史、全部 RAG 文档和全部工具同时传给每个 Agent。

## 5. Tool 实现

每个工具使用 LangChain `@tool` 定义，并通过 `ToolRuntime` 读取当前子图状态。状态写工具返回 `Command(update=...)`；工具内部继续调用 `ToolRegistry` 和 `AgentToolService`，保留现有 guardrail 与确定性结算。

每个 Specialist 使用独立 `ToolNode`：

```text
specialist.model -> specialist.tools -> specialist.model
```

模型只能看到该 Agent 的工具白名单。不要继续创建一个绑定所有 schema 的共享模型，再在运行时仅靠提示词限制工具。

## 6. 路由与持久化

- 父图使用 SQLite checkpointer，负责整个玩家回合、HITL 和恢复。
- Specialist 子图默认 per-invocation，继承父图 checkpointer。
- Director、Rules、Auditor、Narrator、Suggestion 默认无跨回合私有记忆。
- 使用 `Command` 做单路由；只有多个纯只读任务才允许 `Send` 并行。
- 所有可写 Specialist 串行执行，避免 reducer 合并状态时出现冲突。

## 7. 目录结构

```text
backend/agents/
  state.py
  factory.py
  director.py
  rules.py
  exploration.py
  combat.py
  downtime.py
  auditor.py
  narrator.py
  suggestions.py
backend/tools/
  adapters.py
  rules.py
  exploration.py
  combat.py
  campaign.py
backend/workflows/
  dm_workflow.py
```

## 8. 迁移顺序

1. 建立新 State schema、Agent result schema 和 tool adapter，不改变 HTTP API。
2. 迁移 Rules Agent 与 Narrator Agent，验证无写工具边界。
3. 迁移 Exploration Agent，复用现有 ToolRegistry/AgentToolService。
4. 迁移 Combat Agent，并先覆盖当前行动者、伤害去重、施法 DC 和遭遇结束测试。
5. 加入 Director 与 Auditor 的结构化路由和修复循环。
6. 将旧 `_call_model/_execute_tools/_validate_state` 单体循环移除。
7. 更新 SSE，使事件携带 `agent_name`、`subgraph_node`、`tool_name` 和 attempt。

## 9. 验收标准

- 每个 Agent 的模型只绑定自己的工具集合。
- 任一 Agent 无法调用未注册工具，且有自动化测试证明。
- LangGraph trace 能看到独立 Agent 子图和内部 ToolNode。
- Narrator 和 Auditor 没有写工具。
- 同一时刻只有一个可写 Specialist 修改 `GameState`。
- 中断恢复后从原 Agent 子图继续，而不是重跑已提交工具。
- 现有后端回归、SSE、消息重写和浏览器长流程全部通过。

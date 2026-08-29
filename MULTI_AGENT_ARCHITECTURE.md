# DM Agent Loop 架构

本文档描述当前实现，不记录迁移过程。长期决策见 [ADR-0003](docs/adr/0003-single-dm-brain.md)。

## 1. 核心选择

玩家始终面对一个持续身份的 DM Brain。战役阶段只决定上下文、目标和工具能力，不再把主持权交给 Setup、Exploration、Combat 等不同人格。

DM 可以自由进行场景描写、NPC 扮演、节奏控制和临场创作；但机械事实与持久剧情事实必须通过当前阶段允许的确定性工具落地。`GameState` 和成功工具结果仍是权威事实。

在线正确性边界由工具 guardrail、确定性状态不变量和 `finalize_turn` 原子提交组成。运行时没有 Director、LLM Auditor 或独立 Narrator，也不会用第二个模型逐回合审判 DM 的叙事。

## 2. 父图

```text
START
  -> prepare_turn
  -> input_gate
  -> plan_turn
  -> route_phase
  -> rules_context
  -> memory_context
  -> dm_agent
  -> finalize_turn
  -> END
```

- `plan_turn` 计算意图、工具预算和所需规则上下文，不产生另一个主持人格。
- `route_phase` 从权威状态确定阶段，并生成当回合工具白名单。
- `rules_context` 与 `memory_context` 是上下文服务，不是会接管决策的 Agent。
- `dm_agent` 是唯一在线模型角色，既判断行动，也调用工具并完成玩家可见叙事。
- `finalize_turn` 是主回合唯一提交点；失败恢复 `initial_game_state`。

## 3. DM 私有循环

```text
scope -> model -> tools -> validate -> model
                    |          |
                    +----------+----> END
```

DM 拥有完整的确定性工具集合，但 `scope` 会把父图任务子集再次与权威阶段能力取交集。模型一次请求多个工具时只执行第一个，后续调用必须基于新的 `ToolMessage` 和状态继续提出，避免多个写入从同一旧快照竞争。

`validate` 只检查机械不变量，例如当前行动者、动作槽、遭遇状态、角色/战斗镜像和必须完成的状态转换。它不评价文风，也不要求每句叙事提供证据。可安全修复的问题只开放指定工具回到 DM；不可安全修复的问题使事务失败。

DM 模型步只保留三类运行边界：

1. 模型调用或输出为空。
2. 工具轮次预算耗尽。
3. 确定性校验已要求修复，但 DM 没有调用修复工具。

行动选项若混入正文会被展示层清理，不会因此回滚已经正确结算的主回合。

## 4. 工具与事实所有权

`backend/agents/specs.py` 只声明两个运行时角色：

- `dm`：持有所有阶段能力的并集；实际可见工具由 phase allowlist 收窄。
- `suggestions`：提交后的 UI 投影，只持有 `set_player_action_suggestions`。

阶段能力保存在 `PHASE_CAPABILITY_TOOL_NAMES`，角色身份与阶段能力不再混为一谈。工具执行链为：

```text
DM model
  -> StructuredTool / ToolNode
  -> ToolRegistry.validate_call
  -> AgentToolService
  -> GameLogic / RuleCatalog / storage / RAG
  -> ToolMessage + staged GameState
  -> deterministic validate
```

工具 guardrail 负责 schema、阶段、当前行动者、动作槽、法术位、库存、遭遇前置条件和高风险确认。模型不能直接 patch `GameState`。

## 5. 事务、interrupt 与恢复

- 工具产生的状态在 `finalize_turn` 前都属于 staged transaction。
- 高风险工具通过 LangGraph `interrupt()` 暂停，并从同一 checkpoint 恢复。
- `input_required` 只发布上一次已提交的 `GameState` 加 `pending_turn`；staged delta、timeline 和 tool result 不会作为已提交结果返回或保存。
- checkpoint 丢失时终止并回滚挂起事务，要求玩家重新描述行动；“确认”不会被重放成一个新玩家行动。
- checkpoint 只用于执行恢复；剧情分支仍由完整 rewind snapshot 实现。

## 6. 辅助 Agent 协作边界

普通回合不启动额外模型。辅助 Agent 只有在至少满足一项时才值得存在：能引入 DM 当前上下文中没有的新信息、能隔离大量上下文、或能并行完成独立只读工作。

辅助结果必须是只读 brief/artifact，由 DM 决定是否采用；辅助 Agent 不直接写 `GameState`，也不接管玩家对话。当前实现中的 Suggestion Agent 符合这一边界：它在主回合提交后投影三个 UI 行动建议，失败只返回空建议，不影响主事务。

## 7. 运行时拓扑与 trace

`GET /api/v1/health` 的 `agent_topology` 来自已编译工具对象：

```text
dm, suggestions
```

关键 trace：

- `agent.dm.entered`
- `agent.dm.tool_batch_serialized`
- `execute_tools`
- `validate_state`
- `draft_response`
- `finalize_turn`

trace 用于诊断执行，不是逐回合事实审计流程。

## 8. 目录

```text
backend/agents/
  game_master.py     # 持续 DM 的私有 model/tool/validate 循环
  specs.py           # 运行时角色与阶段能力
  state.py           # DM 私有子图状态
  tool_adapters.py   # StructuredTool / ToolRuntime / Command adapter
  suggestions.py     # 提交后 Suggestion 投影
```

父工作流位于 `backend/dm_graph.py`；确定性工具与规则分别位于 `agent_tools.py`、`tool_registry.py`、`game_logic.py` 和 `rules_catalog.py`。

## 9. 变更门禁

新增或修改工具时必须同步 schema、service、guardrail、阶段能力与测试。写工具必须串行，失败不能提交部分状态；涉及 interrupt 时必须验证暂停结果不发布 staged state，且恢复只能继续原事务。

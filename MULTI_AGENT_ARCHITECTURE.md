# DM_Agent 多 Agent 架构

本文档描述当前实现，不记录迁移过程。

## 1. 架构选择

系统采用 LangGraph custom workflow：父图组合确定性节点、结构化控制 Agent 和业务 Specialist 子图。`GameState` 是唯一事实源，所有业务状态变更必须由已注册工具调用 `ToolRegistry`、`AgentToolService` 和 `GameLogic` 完成。

确定性准备、路由保护、验证和原子提交不会伪装成 Agent。行动建议在主回合提交后独立运行，不参与剧情事务。

## 2. 父图

```text
START
  -> prepare_turn
  -> input_gate
  -> director_agent
  -> route_phase
  -> rules_agent
  -> memory_context
  -> specialist(setup | exploration | combat | downtime | level_up)
  -> auditor_agent
       -> selected specialist repair loop
       -> narrator_agent
  -> finalize_turn
  -> END
```

- `prepare_turn`、`input_gate`、`route_phase`、`memory_context` 和 `finalize_turn` 是确定性节点。
- Director、Auditor 和 Narrator 使用独立 `create_agent` 图与结构化输出。
- Rules、五个 Specialist 和 Suggestion 是独立编译的 `StateGraph`。
- 同一回合只有一个可写 Specialist，禁止多个 Agent 并行修改同一份 `GameState`。
- Director 的结果受确定性 phase guard 约束，模型不能把活动战斗路由给 Exploration。

## 3. Agent 契约

### 控制 Agent

- Director：输出唯一 route、目标、规则需求和风险；无工具，不叙事、不写状态。
- Auditor：检查 Specialist 草稿、工具轨迹和权威状态；无工具，拒绝时把问题送回原 Specialist。
- Narrator：把审计通过的事实整理成玩家正文；无工具，不创造事实或行动菜单。

### 只读 Agent

- Rules：私有 `RulesState`，只注册 `lookup_rules`，通过独立 ToolNode 读取本地规则。
- Suggestion：私有 `SuggestionState`，只注册 `set_player_action_suggestions`；候选必须再次通过场景锚点验证，失败返回空建议，不撤销主回合。

### Specialist

- Setup：队伍、角色与冒险准备。
- Exploration：探索、社交、调查、旅行、场景转换和遭遇建立。
- Combat：攻击、施法、状态、先攻、当前行动者、败北和遭遇结束。
- Downtime：恢复、物品、奖励与章节整理。
- Level Up：升级和里程碑选择。

工具全集与所有权以 `backend/agents/specs.py` 为准。`tests/test_agent_factory.py` 检查所有后端 schema 都至少属于一个 Agent，`tests/test_dm_agent_team.py` 检查运行时真实工具表与声明完全一致。

## 4. 子图隔离

每个 Specialist 拥有：

- 私有 `SpecialistState`。
- 独立角色提示词。
- 由 `StructuredTool` 构成的真实工具对象集合。
- 独立 `ToolNode`。
- `scope -> model -> tools -> audit -> model` 有界循环。

父图通过 adapter 把必要字段映射到私有状态，并只接收父图拥有的输出字段。模型绑定当前阶段白名单与 Agent 所有权白名单的交集；工具节点再次执行同样的权限和规则检查。

模型一次可能请求多个工具，但可写工具不会并行执行。Specialist 只放行一个调用，再让模型根据 ToolMessage 请求下一项，从而避免多个 `Command` 基于同一旧状态竞争写入。

## 5. 工具执行

`backend/agents/tool_adapters.py` 把已有 JSON schema 转为 LangChain `StructuredTool`。工具通过 `ToolRuntime` 读取私有状态，并返回 `Command(update=...)`：

```text
model
  -> registered BaseTool
  -> ToolNode
  -> ToolRegistry.validate_call
  -> AgentToolService
  -> GameLogic / storage / RAG
  -> ToolMessage + GameState + trace
```

执行顺序：

1. Agent 所有权和阶段白名单取交集。
2. 校验参数 schema、遭遇状态、当前行动者、动作槽、法术位、库存和确认策略。
3. 高风险工具通过 `interrupt()` 暂停，确认后从原 ToolNode 恢复。
4. 调用框架无关的 `AgentToolService`。
5. 合并 `ToolResult`、timeline、state patch 和 trace。
6. 进入确定性验证；需要修复时仅开放指定工具并回到模型。

`validate_state` 和 Auditor 不直接补写业务状态。可以由工具修复的问题回到 Specialist；不能安全修复的问题让整个回合失败并回滚到 `initial_game_state`。

## 6. 状态与持久化

- 父图使用 `DMGraphState` 和 SQLite checkpointer。
- Specialist 使用 `SpecialistState`，Rules 使用 `RulesState`，Suggestion 使用 `SuggestionState`。
- 子图默认 per-invocation，并在父图调用时继承运行配置，以支持 interrupt 和 durable execution。
- LangGraph checkpoint 用于回合暂停恢复；玩家消息删除和重写使用存档中的 `_rewind` 快照。
- `finalize_turn` 是唯一主回合提交点；失败回合不会提交工具产生的中间状态。

## 7. 运行时审计

`GET /api/v1/health` 的 `agent_topology` 来自已编译 Agent 的实际工具对象，不再直接回显声明。当前角色包括：

```text
director, rules, setup, exploration, combat,
downtime, level_up, auditor, narrator, suggestions
```

关键 trace：

- `agent.<role>.entered`
- `execute_tools`，包含 `agent_name`、工具名、guardrail、确认状态和轮次。
- `validate_state`
- `agent.auditor.completed`
- `agent.narrator.completed`
- `finalize_turn`

## 8. 目录

```text
backend/agents/
  contracts.py       # 结构化控制输出
  factory.py         # create_agent 控制 Agent
  specs.py           # 角色与工具所有权
  state.py           # 私有子图状态
  tool_adapters.py   # BaseTool / ToolRuntime / Command adapter
  specialist.py      # 五个阶段 Specialist
  rules.py           # Rules 子图
  suggestions.py     # Suggestion 子图
```

父工作流仍位于 `backend/dm_graph.py`；确定性工具与规则分别位于 `agent_tools.py`、`tool_registry.py` 和 `game_logic.py`。

## 9. 变更门禁

新增或修改工具时必须同时满足：

1. schema、service 实现和 guardrail 同步。
2. `AGENT_SPECS` 指定合理所有者。
3. 运行时 topology 与声明一致。
4. 未授权 Agent 看不到且不能执行该工具。
5. 写工具保持串行，失败不提交部分状态。
6. checkpoint 暂停恢复、高风险确认、SSE 和消息重写测试通过。
7. 后端全量测试、前端 build/lint 和真实运行时 smoke test通过。

# 术语

| 术语 | 项目中的含义 |
| --- | --- |
| `GameState` | 一局游戏的唯一权威状态，包括角色、场景、战役、遭遇、消息、timeline 和 pending turn。 |
| Parent graph | `DMGraphRunner` 编译的顶层 LangGraph，连接输入、Director、Rules、Specialist、Auditor、Narrator 与提交。 |
| Specialist | 按阶段工作的 Setup、Exploration、Combat、Downtime 或 LevelUp Agent；使用私有子图状态。 |
| Rules agent | 只生成规则检索调用并通过确定性 ToolNode 执行的只读 Agent。 |
| Auditor | 对候选回合做语义一致性复核的控制 Agent；不同于确定性 validator。 |
| Validator / repair | 代码级状态不变量检查；发现可修复问题时要求 Specialist 通过受限工具修复。 |
| `finalize_turn` | 主回合唯一事务提交点；负责成功提交或从初始状态回滚。 |
| Action ledger | 遭遇中 action、bonus action、reaction 的已使用记录及对应工具名。 |
| Current actor | 当前先攻顺序中有权行动的 combatant；不是简单的 active character。 |
| Mirror | `Character` 与其 party `Combatant` 之间必须同步的 HP、状态、defeat、concentration 等字段。 |
| Rewind snapshot | 某条可见消息之前的完整 `GameState`，用于删除和重写剧情分支。 |
| Checkpoint | LangGraph interrupt/resume 的线程状态，不等同于 rewind 或存档分支。 |
| Campaign memory | `campaign_memory.py` 从 `GameState` 派生的有界剧情提示上下文；不是独立事实源，也不同于 `.agent/memory/` 的项目工程记忆。 |
| Action suggestion | 主回合提交后的三个场景化可编辑输入建议；非事务、非合法动作枚举。 |
| Game-scoped monster | 保存在当前 `GameState.monster_templates` 的怪物，与只读标准怪物资产区分。 |
| Model provider | 模型传输方式：OpenAI-compatible API、Claude Code CLI 或 Codex CLI；不改变 Agent 工具所有权。 |
| RAG | 从本地 D&D 文档检索规则片段，仅用于上下文；向量优先，embedding 不可用时降级到词法索引。 |
| Lexical fallback | 对规范化 Markdown/text 做 heading-aware 确定性词法检索；类似 grep，但不依赖操作系统命令。 |

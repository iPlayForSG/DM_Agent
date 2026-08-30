# 术语

| 术语 | 项目中的含义 |
| --- | --- |
| `GameState` | 一局游戏的唯一权威状态，包括角色、场景、战役、遭遇、消息、timeline 和 pending turn。 |
| Parent graph | `DMGraphRunner` 编译的顶层 LangGraph，连接输入装配、持续 DM Brain、确定性校验/修复与提交。 |
| DM Brain | 实时回合中持续身份的唯一 DM；负责判断、工具调用和最终叙事，使用私有子图状态。 |
| Phase capability | Setup、Exploration、Combat、Downtime 或 LevelUp 阶段允许 DM 使用的上下文与工具子集；不是独立 Agent。 |
| Validator / repair | 代码级状态不变量检查；发现可修复问题时要求 DM 通过受限工具修复。 |
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
| RAG | 从本地 D&D 文档检索规则片段，仅用于上下文；默认词法检索，可显式启用向量优先模式。 |
| Lexical retrieval | 对规范化 Markdown/text 做 heading-aware 确定性词法检索；类似 grep，但不依赖操作系统命令，也是默认运行路径。 |

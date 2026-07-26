# 项目特有约定

## 状态与工具

- 所有业务状态以 `GameState` 为准；消息文本不能替代已结算状态。
- Agent 工具通过 `ToolRegistry` schema 与 guardrail 校验，再由 `AgentToolService` 执行。
- Agent role 工具所有权在 `backend/agents/specs.py` 声明；运行时拓扑必须与注册表一致。
- Specialist 私有 state 只能通过 adapter 投影允许字段回父图。
- 写工具串行；不能从同一旧快照并发计算多个 `Command(update=...)`。
- `ToolResult.success=false` 不得产生状态 mutation。

## 回合与错误

- deterministic validation 先于最终提交，修复必须通过工具。
- 模型/provider 错误变成失败 TurnResult，不能让请求崩溃或提交半状态。
- 高风险工具用 interrupt 请求确认；恢复使用同一 thread/checkpoint。
- `finalize_turn` 成功时才推进 `turn_number`；失败时回滚工具变化。
- 回复长度是偏好：最多编辑两次，不通过硬截断破坏 Markdown 或规则事实。

## API 与前端

- API 统一使用 `/api/v1`。
- 前端消费后端的 `action_options`、当前行动者和派生显示字段。
- 异步结果必须通过 game lifecycle、sync request、game id 和 turn number 等守卫，防止旧请求覆盖新存档。
- action suggestions 必须恰好三个、互异、场景特定；仅填充输入框，不自动提交。
- 标准怪物资产只读；游戏内保存使用 game-scoped monster template。

## Schema 与兼容

- Pydantic model 的 before validator 用于旧存档兼容；改字段时保留可验证的迁移路径。
- 角色与其 encounter combatant 是镜像，HP、状态、defeat、concentration 等必须同步。
- 删除/重写从完整 snapshot 恢复，再剪枝未来 snapshot。

## 测试与生成资产

- 测试使用 `unittest`，工作流测试倾向使用 fake model 和临时 checkpoint，避免外部模型依赖。
- `backend/Monsters/*.json` 是跟踪内容资产；不要把它们当运行时生成物批量重写。
- `frontend/dist/`、本地存档、RAG 索引、模型缓存和 runtime logs 不提交。

## 注释

关键状态机、跨层约束、回滚、并发和循环防护使用简体中文解释原因；显而易见代码不逐行注释。

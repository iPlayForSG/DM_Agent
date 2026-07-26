# ExecPlan 任务目录

## 何时创建

以下任务需要 ExecPlan：跨后端/前端或多个规则层、预计多个阶段、包含迁移/架构决策、验证周期较长，或可能跨会话继续。简单文案、单文件小修和明确的一步测试无需创建。

## 命名

使用 `.agent/tasks/YYYY-MM-DD-<task-name>.md`，例如：

```text
2026-07-20-authoritative-spell-saves.md
```

文件内必须有 `Status: active|blocked|completed` 与 `Updated: YYYY-MM-DD`。

## 更新与恢复

- 工作中持续更新 checkbox、决定、意外发现和实际验证结果。
- 恢复时先读 `AGENTS.md`、本 README、相关 plan，再按 plan 指向读取 memory/代码。
- 不依赖聊天记录解释“下一步”；把最短恢复命令和未完成风险写入 Resume instructions。

## 完成与归档

完成后将状态改为 `completed`，保留关键决定和最终验证。计划明显失效且无历史价值时可在独立清理任务中删除；不要在普通实现任务中顺手批量清理历史计划。

规范和模板见 [../PLANS.md](../PLANS.md)。

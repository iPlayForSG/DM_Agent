# Living ExecPlan 规范

ExecPlan 用于复杂、跨模块、多阶段或可能跨会话的工作。它必须让没有聊天历史的下一位 Codex 仅凭仓库即可安全继续。

## 使用规则

1. 文件放在 `.agent/tasks/YYYY-MM-DD-<task-name>.md`，名称使用小写英文和连字符。
2. 开始工作时写入已确认上下文、范围和验证方法。
3. 每完成一个有意义步骤就更新 Progress；发现意外立即写入 Discoveries。
4. Decisions 只记录会影响后续实现的选择及理由。
5. 命令只有实际运行后才能在 Validation 中标记成功。
6. 完成时将 `Status` 改为 `completed`；阻塞时写清阻塞事实和恢复条件。
7. 不复制完整日志、diff、聊天记录或敏感信息。

## 模板

```markdown
# <任务名称>

Status: active | blocked | completed
Updated: YYYY-MM-DD

## Goal

<具体目标>

## User-visible outcome

<用户最终能观察到什么>

## Scope / Non-goals

- In scope: ...
- Non-goal: ...

## Relevant context and files

- `<path>`：<相关原因>

## Progress

- [ ] <步骤>

## Decisions

- YYYY-MM-DD：<决定及理由>

## Discoveries / surprises

- <与原计划不同的事实>

## Validation

- [ ] `<command>` — <预期或实际结果>

## Remaining work

- <下一步>

## Resume instructions

1. <最短恢复路径>
```

计划应是 living document，而不是事后报告；事实变化时修改原条目，不叠加相互矛盾的流水账。

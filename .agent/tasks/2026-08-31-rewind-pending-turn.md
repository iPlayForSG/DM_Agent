# 删除消息后复活失效暂停回合

## Status

已完成。

## Goal

修复玩家取消一次结构化选择、再删除原始玩家消息后，rewind snapshot 复活已经消费过的 `pending_turn`，导致后续任何选择都重复返回“本回合的待定变化均未提交”的问题。

## Root cause

`_execute_turn_and_save` 在恢复暂停回合前，把带有 `pending_turn.thread_id` 的公开回滚状态保存为玩家消息位置的 rewind snapshot。检查点完成或取消后，该 thread 是一次性的；删除玩家消息恢复这个 snapshot 时，前端再次展示选择卡，但 LangGraph 已没有可恢复的活动 interrupt。

## Decisions

- rewind snapshot 表示可重新开始新回合的权威提交状态，不得携带一次性的 `pending_turn`。
- 保存新 snapshot 时清除暂停状态；删除和重写读取旧 snapshot 时再次净化，以兼容已有存档。
- 不自动重放原始输入或用户刚选的选项。无法证明检查点阶段时只恢复提交状态，由玩家重新描述行动。

## Progress

- [x] 在浏览器复现当前 `111` 存档的失效选择卡。
- [x] 定位 `_execute_turn_and_save` 保存了带暂停状态的 base snapshot。
- [x] 实现 rewind snapshot 净化。
- [x] 添加恢复暂停、删除和重写的 API 回归测试。
- [x] 完成测试与浏览器修复验证。

## Validation

- 新增 3 条针对性回归：旧 snapshot 删除、暂停恢复后删除、旧 snapshot 重写，全部通过。
- `python -m unittest tests.test_main_streaming -v`：16 项通过。
- `python -m unittest discover -s tests -v`：最终 211 项通过。沙箱内首次运行因默认 Python 缺少项目依赖且 Windows 系统临时目录受限而失败；改用项目环境并允许正常临时目录访问后原命令全量通过。
- `npm run build`：通过（Vite 288 个模块）。
- `npm run lint`：0 error；保留仓库原有 2 条 Hook dependency warning。
- `git diff --check`：通过，仅有 LF/CRLF 提示。
- 浏览器真实恢复 `111`：先终止旧暂停，再删除消息索引 7；返回 `rewound`、`pending_turn=false`、可见消息 7 条。重新进入存档后原行动、取消回复和选择卡均消失，输入框可用。

## Remaining work

无。

## Resume instructions

任务已完成；后续新增 rewind 入口时统一通过 `_rewind_safe_state` 清除一次性暂停状态。

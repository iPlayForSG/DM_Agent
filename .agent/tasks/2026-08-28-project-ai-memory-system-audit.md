# 项目级 AI 记忆系统兼容性审计

Status: completed
Updated: 2026-08-28

## Goal

按附件完成标准审计并补齐仓库现有的项目级 AI 记忆系统，确认其与当前项目结构及 `codex-cli 0.146.0` hooks 行为兼容。

## User-visible outcome

后续 Codex 可继续通过 `AGENTS.md`、按需 memory、living ExecPlan、ADR 和项目 hooks 恢复上下文；高信号变化能触发一次且不会形成 Stop 循环。

## Scope / Non-goals

- In scope：项目文档、`.agent/`、ADR、`.codex/` hook 配置、策略、脚本与测试。
- Non-goal：产品功能代码、用户级 `~/.codex/`、外部记忆服务、Git commit。

## Relevant context and files

- `AGENTS.md`：稳定项目入口及维护协议。
- `.agent/memory/`：当前项目事实与命令。
- `.codex/hooks.json`、`.codex/memory-policy.json`、`.codex/hooks/`：生命周期配置、路径策略和确定性实现。
- `.agent/tasks/2026-07-20-project-ai-memory-system.md`、`docs/adr/0001-project-ai-memory-system.md`：原始实现记录和已接受边界。

## Progress

- [x] 读取附件、当前 `AGENTS.md`、原始 ExecPlan、ADR、memory、hooks 与测试。
- [x] 核对本机 `codex-cli 0.146.0` feature 状态及当前官方 hooks release behavior。
- [x] 运行现有 hook 测试，确认 20 项通过。
- [x] 补齐相对当前项目结构发生漂移的路径策略、命令记忆和对应测试。
- [x] 完成 JSON、合成事件、链接、diff 与 Git 状态验证。

## Decisions

- 2026-08-28：保守整合现有实现，不创建竞争性的第二套记忆结构。
- 2026-08-28：保留 2026-07-20 已完成计划的历史验证事实；本次版本兼容性结果写入独立审计计划。

## Discoveries / surprises

- 仓库已包含附件要求的完整结构，工作树开始时为干净状态。
- 官方 manual helper 因 shell DNS 受限无法拉取；官方 Hooks release behavior 与本机可执行结果均确认当前协议仍支持。
- 当前官方 `SessionStart.source` 还包含 `clear`；清空会话必须建立新基线，不能沿用被清空上下文的观察窗口。
- `backend/encounter_math.py` 已进入模块记忆，但尚未进入 `.codex/memory-policy.json` 的高信号路径。
- README 已定义 RAG 索引构建命令，`.agent/memory/commands.md` 尚未同步。
- `campaign_memory.py` 的剧情提示记忆与 `.agent/memory/` 的项目工程记忆概念相近但所有权不同，已在模块和术语记忆中明确区分。
- `codex --strict-config features list` 不受该子命令支持，不能作为 hooks 配置验收命令；JSON、官方事件协议和真实入口脚本测试已覆盖本次需要的配置边界。

## Validation

- [x] `python3 -m unittest discover -s .codex/hooks/tests -v` — 20 tests passed（补齐前基线）。
- [x] `python3 -m unittest discover -s .codex/hooks/tests -v` — 25 tests passed。
- [x] `python3 -m json.tool .codex/hooks.json`
- [x] `python3 -m json.tool .codex/memory-policy.json`
- [x] 合成 SessionStart、PostToolUse、Stop stdin 事件 — 均退出 0 并输出合法 JSON；continuation 与循环防护由 subprocess 测试覆盖。
- [x] Markdown 相对链接检查 — 全部存在。
- [x] Hook 配置中的 POSIX/Windows 入口路径检查 — 脚本均存在并从 Git 根解析。
- [x] `git diff --check`
- [x] `git status --short --branch` — 仅本任务允许的文档、`.agent/`、`.codex/` 与 hook 测试发生变化，未出现临时状态或产品代码修改。

## Remaining work

- 用户需在 Codex CLI 使用 `/hooks` 审查并信任本次变更后的项目 hook 哈希。

## Resume instructions

任务已完成。未来 Codex hooks 事件协议或主要模块边界变化时，先读本计划、`docs/adr/0001-project-ai-memory-system.md` 和 `.codex/hooks/tests/`。

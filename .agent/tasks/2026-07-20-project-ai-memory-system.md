# 初始化项目级 AI 记忆系统

Status: completed
Updated: 2026-07-20

## Goal

为 DM_Agent 建立仓库内、按需加载、可跨会话恢复且由 Codex hooks 增量校准的项目记忆系统。

## User-visible outcome

后续 Codex 从 `AGENTS.md` 进入项目，按需读取 memory，使用 living ExecPlan 和 ADR，并在高信号代码变化后自动进入一次文档维护回合。

## Scope / Non-goals

- In scope：项目文档、`.agent/`、ADR、`.codex/hooks.json`、Python 标准库 hook 与测试。
- Non-goal：修改 DM_Agent 产品功能、用户级 `~/.codex/`、外部记忆服务或 Git commit。

## Relevant context and files

- `README.md`、`MULTI_AGENT_ARCHITECTURE.md`：跟踪的项目文档。
- `backend/main.py`、`backend/models.py`、`frontend/src/api.js` 和 API 测试：接口事实源。
- 初始化时存在的本地 API/走查文档：一次性设计输入；稳定事实已提炼进 memory，重复文件随后移除。
- `.codex/hooks/`：确定性检测实现。

## Progress

- [x] 调查仓库、文档、命令、工作树和 Codex 0.142.5 hook 能力。
- [x] 创建 `AGENTS.md`、按主题 memory、ExecPlan 和 ADR 机制。
- [x] 实现 SessionStart、PostToolUse、Stop 与指纹循环防护。
- [x] 编写并运行临时 Git 仓库测试和合成事件验证。
- [x] 检查 JSON、命令路径、Markdown 链接、临时状态和 Git diff。

## Decisions

- 2026-07-20：状态优先放入 `git rev-parse --git-path codex-memory-hook`；只读 Git 目录时使用按 git-path 哈希隔离的系统临时目录，兼容普通仓库/worktree 且不污染工作树。
- 2026-07-20：Hook 只做路径、基线和指纹判断；语义维护由 Stop continuation 中的当前 Codex 完成。

## Discoveries / surprises

- 初始化时的重复设计文档与本地 handoff 被 `.gitignore` 忽略，其中部分内容已经落后于当前未提交代码。
- 官方 manual helper 在当前网络环境失败；改用官方 OpenAI Docs MCP 的 Hooks release behavior 页面核对协议。
- 当前工具沙箱对真实仓库 `.git` 只读；真实合成事件已验证临时目录降级路径。

## Validation

- [x] `python -m unittest discover -s .codex/hooks/tests -v` — 20 tests passed。
- [x] 合成 SessionStart、PostToolUse、Stop stdin 事件 — Windows 命令均输出合法 JSON。
- [x] `python -m json.tool .codex/hooks.json`
- [x] `python -m json.tool .codex/memory-policy.json`
- [x] `git diff --check`

## Remaining work

- 用户需在 Codex CLI 使用 `/hooks` 审查并信任项目 hook 哈希。

## Resume instructions

任务已完成。Hook 行为变化时先读 `docs/adr/0001-project-ai-memory-system.md` 和 `.codex/hooks/tests/`。

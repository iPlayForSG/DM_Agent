# ADR-0001：项目级 AI 记忆采用仓库文档与确定性 Hooks

Status: Accepted
Date: 2026-07-20

## Context

DM_Agent 是长期、多模块项目，复杂任务需要跨会话恢复。聊天历史不稳定，现有部分设计文档又被 `.gitignore` 忽略且已经出现漂移。项目需要可审查、可移植的长期知识入口，并在重要代码变化后提醒维护，但不能让 hook 自行调用模型、递归启动 Codex 或机械改文档。

## Decision

- 使用根 `AGENTS.md` 作为稳定入口，`.agent/memory/` 保存按主题加载的高信号事实。
- 使用 `.agent/tasks/` living ExecPlan 恢复复杂工作，`docs/adr/` 记录重大长期决策。
- 使用仓库级 `.codex/hooks.json` 配置 `SessionStart`、`PostToolUse` 和 `Stop`。
- Hook 用 Python 3 标准库和 Git 做确定性基线、路径分类和 diff 指纹；状态优先存放在 `git rev-parse --git-path codex-memory-hook`，只读沙箱中降级到按该路径哈希隔离的系统临时目录。
- `Stop` 只在高信号变化时使用当前 Codex continuation 进行语义判断；不执行 `codex exec` 或外部 LLM。
- `stop_hook_active`、已审计指纹和每指纹一次触发上限共同阻止维护循环。

## Alternatives considered

- 依赖聊天历史：无需代码，但不可移植、不可审查，压缩或新会话后容易丢失。
- RAG/向量数据库/外部记忆服务：检索能力更强，但引入额外运行时、隐私和事实同步问题，超出项目级工程记忆需求。
- Hook 直接启动新的 Codex：自动化更强，但会递归、绕开当前回合权限和信任边界。
- 每次修改都更新文档：简单但噪声高，容易形成机械、过期的流水账。

## Consequences

- 项目知识可通过 Git 审查并按需加载，复杂任务可跨会话恢复。
- Hook 只能作为提醒和校准闸门，不能证明文档或产品行为正确。
- 路径策略需要随模块边界变化维护；项目 hook 哈希变化后需要重新信任。
- 语义判断仍由当前 Codex 回合完成，并允许结论为“无需更新”。

## Validation / follow-up

- 自动化测试覆盖基线、dirty file、路径分类、worktree、指纹和 Stop 循环防护。
- 合成事件验证三个 hook 的 JSON 输入/输出。
- 发布或大型合并后运行 `.agent/prompts/full-memory-audit.md`。

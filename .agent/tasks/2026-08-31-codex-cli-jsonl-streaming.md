# Codex CLI JSONL 流式适配

Status: active
Updated: 2026-08-31

## Goal

让 `CodingAgentCLIChatModel` 通过 `codex exec --json` 持续消费 JSONL 事件并实现 LangChain `_stream()`，同时保持结构化正文和工具调用协议不变。

## User-visible outcome

Codex CLI 一旦提供可公开的文本增量，主持思考区会立即增长；无论是否有增量，最终正文和工具调用都与非流式调用一致。

## Scope / Non-goals

- In scope：`backend/model_backends.py` 的 Codex JSONL 进程生命周期、事件解析、超时/错误处理、`AIMessageChunk` 聚合和 adapter 契约测试。
- Non-goal：不把 UI 打字动画冒充 provider 流式；不改变 Claude Code transport；不改变确定性工具或 `finalize_turn` 边界。

## Relevant context and files

- `backend/model_backends.py`：当前 Codex 只用 `subprocess.run(capture_output=True)` 实现 `_generate()`。
- `backend/dm_graph.py`：SSE 上下文已经调用 `model.stream()` 并聚合 `BaseMessageChunk`。
- `tests/test_model_backends.py`：现有 CLI 结构化工具调用契约测试。
- `.agent/tasks/2026-08-31-live-dm-thinking-stream.md`：上游 SSE 与前端思考区已完成。

## Progress

- [x] 核对本机 LangChain `BaseChatModel._stream()` 契约。
- [x] 采样 Codex CLI 0.147.0 的真实 `--json` 输出并核对官方 exec 事件源码。
- [x] 实现 JSONL `_stream()` 与结构化结果聚合。
- [x] 增加模拟及真实 CLI adapter 契约测试。
- [ ] 完成提交并推送。

## Decisions

- 2026-08-31：`_stream()` 产出 `ChatGenerationChunk(AIMessageChunk)`；工具调用只从最终通过 schema 校验的 agent message 重建，不能从中间文本猜测参数。
- 2026-08-31：不把完成后拆字显示视为真实流式；当前 CLI 无 agent delta 时只报告 transport 限制。

## Discoveries / surprises

- Codex CLI 0.147.0 的实测成功流为 `thread.started → turn.started → item.completed(agent_message) → turn.completed`，短回复没有文本 delta。
- 官方 `codex-rs/exec` 当前只在 `item.completed` 映射 agent message；app-server 的 `item/agentMessage/delta` 没有透传到 exec JSONL。

## Validation

- [x] `python -m unittest tests.test_model_backends -v`：6 项通过，其中真实 CLI 项在常规模式跳过。
- [x] 项目 Conda 环境完整后端测试：229 项通过，1 项真实 CLI 测试按预期跳过。
- [x] `npm run build`：通过；`npm run lint`：0 errors、2 个既有 Hook dependency warnings。
- [x] 真实 `codex exec --json` adapter：使用 Codex CLI 0.147.0、`gpt-5.6-luna`/low 通过，且 `ResourceWarning` 提升为错误后仍通过。
- [x] `.codex/hooks/tests`：25 项通过；前端语义纯状态测试：4 项通过。
- [ ] `git diff --check`、提交与推送。

## Remaining work

- 完成最终差异检查、提交并推送。

## Resume instructions

从 `backend/model_backends.py` 的 Codex 分支开始；保留 Claude `subprocess.run`，并确保异常时终止子进程且错误详情脱敏。

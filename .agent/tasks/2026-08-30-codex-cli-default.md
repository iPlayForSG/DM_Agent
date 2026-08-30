# Codex CLI 默认模型接入

Status: completed
Updated: 2026-08-30

## Goal

把 DM_Agent 的未配置默认模型传输切换为本机 Codex CLI，并明确固定 `gpt-5.6-terra` 与 `high` 推理强度；验证应用适配器能真实拉起已登录的本地 CLI。

## User-visible outcome

新配置默认显示并使用 Codex CLI、`gpt-5.6-terra` 和 `high`。现有模型档案仍可切换到 OpenAI-compatible API 或 Claude Code，Codex 子进程继续只能作为受限模型传输层运行。

## Scope / Non-goals

- In scope：CLI 命令构造、模型档案/API/UI 默认值、推理强度配置、真实 CLI smoke、测试与必要文档。
- Non-goal：修改用户级 Codex 配置、保存新的模型凭据、允许 Codex 操作仓库或游戏状态、移除其它 provider。

## Relevant context and files

- `backend/model_backends.py`：Codex CLI subprocess 命令与结构化输出协议。
- `backend/agent.py`：默认 provider、模型档案和本地持久化。
- `backend/dm_graph.py`：把模型档案参数传给 LangChain CLI 适配器。
- `backend/main.py`、`frontend/src/App.jsx`：模型设置 API 与 UI。
- `tests/test_model_backends.py`、`tests/test_llm_profiles.py`：CLI 命令和档案契约。

## Progress

- [x] 读取项目协议、模型传输 ADR、相关 memory 和既有 CLI 任务。
- [x] 确认本机 `codex-cli 0.147.0` 可执行。
- [x] 用 `gpt-5.6-terra` 与 `model_reasoning_effort=high` 完成一次真实非交互调用，返回预期文本。
- [x] 实现 Codex CLI / Terra / high 默认值及配置透传。
- [x] 更新当前本地应用档案，并执行目标、全量、前端与真实适配器验证。
- [x] 更新稳定文档和最终验证记录。

## Decisions

- 2026-08-30：默认值由项目显式传入，不依赖用户级 `~/.codex/config.toml`，避免开发机配置漂移。
- 2026-08-30：Codex 子进程使用 `--ignore-user-config` 与 `--ignore-rules`，但继续复用 `CODEX_HOME` 登录态；这样不会加载与游戏模型传输无关的插件、MCP 或指令。
- 2026-08-30：CLI 健康接口仍只做无费用的安装检查，真实登录态和模型可用性由本次 smoke 及实际回合验证。

## Discoveries / surprises

- 首次显式 Terra/high smoke 成功，但现有命令加载了用户级插件/MCP，出现无关 HTTP 502，且简单响应消耗约 18k 输入 token；适配器需要隔离用户配置而不仅是临时工作目录。
- 官方 OpenAI 文档检索本次未返回可用页面；参数契约改由本机 CLI 0.147.0 的 `exec --help` 与真实成功调用验证。

## Validation

- [x] `codex --version` — `codex-cli 0.147.0`。
- [x] `codex exec ... --model gpt-5.6-terra -c model_reasoning_effort=\"high\"` — exit 0，返回 `DM_AGENT_CODEX_OK`。
- [x] 项目 Python 目标测试 — CLI/profile/runner 9 项成功。
- [x] `python -m unittest discover -s tests -v` — 199 项成功。
- [x] `npm run build` — 成功。
- [x] `npm run lint` — 0 errors，2 条既有 Hook dependency warning。
- [x] `git diff --check` — 通过，仅有工作区 LF/CRLF 提示。
- [x] `git status --short --branch` — 仅本任务代码、测试、文档和 ExecPlan 发生变化；本地 `.env` 保持忽略。
- [x] `CodingAgentCLIChatModel` 真实结构化 smoke — 返回 `DM_AGENT_ADAPTER_OK`，0 个工具调用，未再加载用户插件/MCP。
- [x] 当前本地模型档案 — `codex-cli`、`gpt-5.6-terra`、`high`、命令 `codex`；安装检查识别 `codex-cli 0.147.0`。

## Remaining work

- 无。

## Resume instructions

任务已完成。未来升级 Codex CLI 或默认模型时，先核对本机 `codex exec --help`，再运行 CLI/profile 目标测试与 `CodingAgentCLIChatModel` 合成 smoke；不要依赖或输出用户级 Codex 配置和凭据。

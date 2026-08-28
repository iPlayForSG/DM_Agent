# CLI 模型接入与 Grep 规则检索降级

Status: active
Updated: 2026-08-28

## Goal

在保留 OpenAI-compatible API 模式的基础上，新增 Claude Code 与 Codex CLI 模型后端；当 embedding/Chroma 不可用时，使用规范化本地规则语料和确定性词法检索继续提供知识库上下文，并补齐 macOS/Windows 跨平台运行边界。

## User-visible outcome

用户可在现有模型配置界面选择 API、Claude Code CLI 或 Codex CLI；规则检索会公开当前 backend，并在向量检索不可用时自动降级到本地词法检索，而不是直接失效。

## Scope / Non-goals

- In scope：模型 provider 抽象、CLI subprocess 适配、配置 API/UI、RAG fallback、规则文档规范化工具与规范、跨平台启动/测试、必要文档。
- Non-goal：让 coding agent CLI 直接改写游戏状态或绕过 LangGraph 工具边界；提交规则书全文；替用户安装/登录 Claude Code 或 Codex；修改现有确定性规则语义。

## Relevant context and files

- `backend/agent.py`：当前 API profile、持久化和 runner 重建入口。
- `backend/dm_graph.py`、`backend/agents/`：LangChain chat model 与 tool calling/structured output 消费方。
- `backend/rag.py`、`backend/rag_embeddings.py`、`backend/rag_ingest.py`：向量检索、GGUF server 和语料切片。
- `backend/main.py`、`frontend/src/api.js`、`frontend/src/App.jsx`：模型配置和 RAG 状态的用户入口。
- `backend/Documents/`、`backend/Knowledge/`：被 Git 忽略的原始规则资料和生成知识资产。

## Progress

- [x] 创建并切换分支 `feat-cli-model-and-grep-rag`，保留会话开始前已有记忆系统改动。
- [x] 读取项目约束和相关 memory，定位 API profile、LangGraph model、RAG 与前端配置入口。
- [x] 检查本机 CLI：`codex-cli 0.146.0`、Claude Code `2.1.238` 均可执行。
- [x] 确认本机 `backend/Documents/` 当前没有规则书文件，不能虚构已完成正文整理。
- [x] 核对 Codex/Claude 官方非交互与结构化输出契约，形成 provider 设计。
- [x] 实现 provider、配置/UI、grep fallback、规范化工具和测试。
- [x] 完成后端/前端/跨平台验证与文档维护；实际规则书人工复核等待本地语料。

## Decisions

- 2026-08-28：使用描述性分支名 `feat-cli-model-and-grep-rag`，不采用字面占位名 `feat-xxx`。
- 2026-08-28：原始规则书保持只读；规范化副本写入被忽略的本地知识目录，避免破坏来源或把全文带入 Git。
- 2026-08-28：CLI 只能作为模型传输层，必须返回 LangChain 可消费的内容/工具调用；不能授权 CLI 自行执行游戏写操作。
- 2026-08-28：运行时词法降级使用纯 Python heading-aware 索引，不依赖系统 `grep`/`rg`，以保证 Windows/macOS 的转义、编码和安装一致性。
- 2026-08-28：CLI 健康检查只验证本机安装与版本，不触发付费模型请求；UI 明确说明登录态在首次真实调用时验证。

## Discoveries / surprises

- 当前 Mac 的系统 `python3` 未安装 `fastapi` 等项目依赖；需要建立可复现的 POSIX 环境后才能运行完整后端测试。
- `rag_embeddings.py` 默认寻找 `llama-server.exe` 和 CUDA 目录，当前实现明显偏 Windows，需要把可执行文件解析改为平台中立。
- CLI 每个图节点都可能启动一个子进程，正确性可以先支持，但真实回合的延迟与费用必须通过 smoke 单独验证。
- 全量后端 169 个测试当前有 13 个既有失败，均因被 `.gitignore` 排除的 `backend/data/spells.json` 在这台 Mac 缺失，表现为法术目录为空；新增 10 个目标测试全部通过。
- 初次 macOS 启动 smoke 暴露了“未配置 API 时 health 构建模型并抛错”的旧路径；runner 现按档案完整性决定是否启用模型节点，无配置启动与健康接口已通过。
- Codex 的严格 output schema 首次拒绝任意对象型工具参数；协议改为 `args_json` 字符串后，Codex/Claude 真实文本调用与 Codex 真实 `lookup_rules` tool call 均通过。

## Validation

- [x] CLI provider 单元测试（命令构造、结构化响应、tool calls、安装探测、凭据隔离）。
- [x] RAG fallback 与文档规范化单元测试。
- [x] `python -m unittest discover -s tests -v`（169 tests；156 通过，13 个因 ignored 法术目录缺失而失败）
- [x] `python -m unittest discover -s .codex/hooks/tests -v`（25 tests 通过）
- [x] `npm run build`
- [x] `npm run lint`（0 error，2 个会话开始前已有 hooks dependency warning）
- [x] macOS `start.sh`、health/config/RAG status smoke
- [x] Codex/Claude Code 真实结构化文本 smoke；Codex 真实 tool-call smoke
- [x] `git diff --check`
- [x] `git status --short --branch`（确认仍在 `feat-cli-model-and-grep-rag`，继承的 memory/hook dirty changes 未被覆盖）

## Remaining work

- 将规则书放入 `backend/Documents/DND5e 2024/` 后运行规范化脚本，并人工复核标题、aliases、OCR 和表格；当前目录为空，无法在本次会话执行正文整理。

## Resume instructions

1. 读取本计划与 `.agent/memory/architecture-map.md`、`module-map.md`、`common-pitfalls.md`。
2. 继续最终验证、diff review、memory 最小更新；不要修改缺失的本地法术资产来掩盖基线失败。
3. 不读取或输出 `backend/.env`；测试使用 `DM_AGENT_SKIP_DOTENV=1`、临时目录和 fake subprocess。

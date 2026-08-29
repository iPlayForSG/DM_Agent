# CLI 模型接入与 Grep 规则检索降级

Status: completed
Updated: 2026-08-29

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

- [x] 创建功能分支；远端现已规范命名为 `feat/cli-model-and-grep-rag`。
- [x] 读取项目约束和相关 memory，定位 API profile、LangGraph model、RAG 与前端配置入口。
- [x] 检查本机 CLI：`codex-cli 0.146.0`、Claude Code `2.1.238` 均可执行。
- [x] 确认本机 `backend/Documents/` 当前没有规则书文件，不能虚构已完成正文整理。
- [x] 核对 Codex/Claude 官方非交互与结构化输出契约，形成 provider 设计。
- [x] 实现 provider、配置/UI、grep fallback、规范化工具和测试。
- [x] 完成后端/前端/跨平台验证与文档维护；实际规则书人工复核等待本地语料。
- [x] 在 Windows 工作区确认 `backend/Documents/DND5e 2024/` 已有 2,948 个 Markdown 文档（约 12.7 MB）。
- [x] 生成规范化词法语料并完成标题、aliases、OCR 与表格质量抽查。

## Decisions

- 2026-08-28：使用描述性分支名 `feat-cli-model-and-grep-rag`，不采用字面占位名 `feat-xxx`。
- 2026-08-28：原始规则书保持只读；规范化副本写入被忽略的本地知识目录，避免破坏来源或把全文带入 Git。
- 2026-08-28：CLI 只能作为模型传输层，必须返回 LangChain 可消费的内容/工具调用；不能授权 CLI 自行执行游戏写操作。
- 2026-08-28：运行时词法降级使用纯 Python heading-aware 索引，不依赖系统 `grep`/`rg`，以保证 Windows/macOS 的转义、编码和安装一致性。
- 2026-08-28：CLI 健康检查只验证本机安装与版本，不触发付费模型请求；UI 明确说明登录态在首次真实调用时验证。
- 2026-08-29：同名文件的生成标题使用最短必要父目录消歧；显式 document title override 仍保持最高优先级。
- 2026-08-29：书名和 PHB/DMG/MM 等公共别名使用可继承的 directory aliases，并让词法索引把 aliases 应用于文档的每个 heading chunk。
- 2026-08-29：原始规则书继续只读；能确定列数的表格分隔错误只在生成副本修复，不能可靠自动还原的折叠表格与过短来源写入 manifest quality warnings。

## Discoveries / surprises

- 当前 Mac 的系统 `python3` 未安装 `fastapi` 等项目依赖；需要建立可复现的 POSIX 环境后才能运行完整后端测试。
- `rag_embeddings.py` 默认寻找 `llama-server.exe` 和 CUDA 目录，当前实现明显偏 Windows，需要把可执行文件解析改为平台中立。
- CLI 每个图节点都可能启动一个子进程，正确性可以先支持，但真实回合的延迟与费用必须通过 smoke 单独验证。
- 全量后端 169 个测试当前有 13 个既有失败，均因被 `.gitignore` 排除的 `backend/data/spells.json` 在这台 Mac 缺失，表现为法术目录为空；新增 10 个目标测试全部通过。
- 初次 macOS 启动 smoke 暴露了“未配置 API 时 health 构建模型并抛错”的旧路径；runner 现按档案完整性决定是否启用模型节点，无配置启动与健康接口已通过。
- Codex 的严格 output schema 首次拒绝任意对象型工具参数；协议改为 `args_json` 字符串后，Codex/Claude 真实文本调用与 Codex 真实 `lookup_rules` tool call 均通过。
- 原计划所在 Mac 没有规则语料，但当前 Windows 工作区已有完整 Markdown 集合；应以本机实际文件继续规范化，不再把“目录为空”视为当前阻塞。
- Windows 语料初次生成出现 317 个重复标题组中的同名文档、2 个可确定修复的表格分隔错误，以及 5 条折叠表格长行；标题消歧和分隔修复后，manifest 中 2,948 个标题全部唯一，折叠表格不再污染 heading。
- 全语料未发现 Unicode replacement character、常见乱码、HTML 标签或 HTML entity 残留；4 个不足 40 字符的来源和 5 条仍折叠的表格长行由 manifest 持续提示人工维护。
- 目录 aliases 若只写入文档头部，无法影响后续 heading chunk；索引需在所有 chunk 上继承并单独加权，`MM dragon` 才能稳定命中核心怪物图鉴。

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
- [x] `git status --short --branch`（历史验证时仍在旧名分支；当前分支名为 `feat/cli-model-and-grep-rag`）
- [x] Windows 规则语料规范化：2,948 documents、2,948 unique titles、1,149 aliased documents；重复执行 manifest SHA-256 均为 `AEE9637A14A6CC3E4772E3364292DFEC26E3CD5CA1CFB2FF998A32804D243FB5`。
- [x] 全语料质量扫描：0 encoding/HTML artifacts、0 output/header mismatch、0 table header/separator mismatch；manifest 保留 5 个 `flattened-table-line` 与 4 个 `short-source` 警告。
- [x] 真实词法索引：2,948 documents、8,727 chunks；中文/英文术语及 `PHB combat`、`DMG magic items`、`MM dragon` 查询命中对应核心规则来源。
- [x] `python -m unittest tests.test_rag_fallback -v`（9 tests 通过）。
- [x] 项目 Conda Python `python -m unittest discover -s tests -v`（174 tests 通过）。
- [x] 项目 Conda Python `python -m unittest discover -s .codex/hooks/tests -v`（25 tests 通过）。
- [x] Windows `npm run build`；`npm run lint`（0 error，2 个既有 hooks dependency warning）。

## Remaining work

- 无必需工程工作。被忽略的本地原始语料仍有 5 条折叠表格长行和 4 个过短来源；后续人工修订这些来源后重新运行规范化脚本，并以 manifest quality warnings 归零为目标。

## Resume instructions

任务已完成。未来本地规则来源变化时，运行 `python backend/utils/normalize_rule_documents.py`，检查 manifest 的 `quality_warning_counts`，再用核心中英文术语和 PHB/DMG/MM 缩写做词法 smoke；不要提交原始或生成的规则书正文。

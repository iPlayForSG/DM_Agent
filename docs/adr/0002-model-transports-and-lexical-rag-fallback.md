# ADR-0002：模型传输可选择 API 或 Coding Agent CLI，规则检索默认使用词法索引

Status: Accepted
Date: 2026-08-28

## Context

DM_Agent 原先只通过 OpenAI-compatible API 调用模型，并依赖 Chroma 与本地 GGUF embedding 完成规则检索。开发与运行环境同时覆盖 Windows 和 macOS；本地 embedding 模型、CUDA 版 llama.cpp 或向量索引可能不存在，但规则问答不能因此完全失效。用户也可能已经登录 Claude Code 或 Codex，希望复用本机 CLI，而不是再配置一套 API 凭据。

模型仍不得直接改写 `GameState`。Coding Agent CLI 通常具有文件和命令工具，因此若把它作为自主 Agent 直接接入，会越过项目已有的工具所有权、阶段白名单、审计和回滚边界。

## Decision

- 模型档案明确记录 provider：`openai-compatible`、`claude-code` 或 `codex-cli`。
- 未配置模型档案时默认使用 Codex CLI、`gpt-5.6-terra` 与 `high` 推理强度；用户仍可显式选择其它 provider 或模型。
- Claude Code 与 Codex 通过 LangChain `BaseChatModel` 适配器接入，只承担对话与结构化工具调用传输。
- 每次 CLI 调用使用独立临时工作目录。Claude Code 禁用自身工具和会话持久化；Codex 使用 ephemeral、read-only sandbox，并忽略用户级配置与规则，只复用 `CODEX_HOME` 登录态。CLI 只返回应用工具调用，成功的确定性工具仍是改变权威状态的唯一入口。
- CLI 健康检查只运行 `--version` 并明确标记为安装检查；认证与真实模型调用在首次请求时验证。
- 规则检索默认使用纯 Python、heading-aware 的确定性词法索引，不加载 Chroma 或调用 embedding。只有显式设置 `RAG_RETRIEVAL_MODE=vector` 才优先使用 Chroma/GGUF；向量库或查询 embedding 不可用时仍自动回退词法索引，两者都不可用时才报告 RAG 未就绪。
- 原始规则书保持只读且不入 Git。规范化工具生成 UTF-8 Markdown 副本与 manifest 到被忽略的 `backend/Knowledge/grep_corpus/`，并用 tracked overrides 保存标题与搜索别名。
- llama.cpp 可执行文件同时支持 PATH、无后缀 POSIX 文件和 `.exe`，macOS 默认采用自动设备策略；Windows CUDA 目录继续作为兼容候选。

## Alternatives considered

- 只保留 API：边界最简单，但不能复用已安装和登录的 Coding Agent CLI。
- 让 Claude Code/Codex 自主操作仓库和游戏文件：能力更强，但会绕过确定性状态机、审计和回滚，故不采用。
- 在 embedding 缺失时直接关闭 RAG：实现简单，但规则书明明在本地仍无法检索。
- 直接调用系统 `grep` 或 `rg`：性能好，但命令可用性、参数转义和中文行为跨平台不一致；采用等价的纯 Python 词法索引作为运行时依赖。
- 原地改写原始规则书：避免重复存储，但破坏来源保真与可恢复性，也增加误提交版权资料的风险。

## Consequences

- 用户可在同一 UI 保存和切换三种模型档案，API 凭据不会传给 CLI 子进程。
- 新安装默认依赖本机 Codex CLI 已安装并登录；不满足时用户需要先登录 Codex，或在模型设置中切换到 API/Claude Code 档案。
- CLI 每个模型节点都会启动独立进程，延迟通常高于直接 API；真实登录态、费用与模型兼容性仍需各环境 smoke test。
- 词法检索不具备 embedding 的语义召回能力，质量更依赖规范标题、术语、别名和人工 OCR 清理。
- 默认词法模式不会把未加载向量报告为错误或 fallback；显式向量模式查询失败时不会中断规则检索，状态接口会保留 vector error 和 fallback reason，避免静默掩盖故障。
- 原始语料变化后需要重新运行规范化工具；规则正文仍由本地持有者负责授权和人工校对。

## Validation / follow-up

- 单元测试覆盖 CLI 命令约束、结构化文本/工具调用转换、安装探测、档案凭据隔离、文档规范化以及两类词法降级。
- Windows 与 macOS 分别验证启动脚本、CLI 登录态和至少一个真实回合。
- 有实际规则书语料后运行规范化工具，人工抽查标题、别名、OCR、表格和典型规则查询。

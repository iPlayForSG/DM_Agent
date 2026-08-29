# DM_Agent 项目指南

## 项目概览

DM_Agent 是本地优先的 D&D 2024 单人跑团应用。React/Vite 前端通过 FastAPI API 操作游戏；LangGraph 中持续身份的 DM Brain 负责理解、规划和叙事，确定性 Python 规则层负责骰子、战斗、资源和持久化。

核心边界：LLM 可以提出意图和工具调用，但不能直接改写权威游戏事实。`GameState` 以及成功执行的确定性工具结果才是运行时事实。

## 事实源与冲突处理

按以下顺序判断事实：

1. 当前代码、测试、配置和实际运行结果。
2. `docs/adr/` 中状态为 `Accepted` 的 ADR。
3. 已验证且仍适用的 `.agent/memory/`。
4. 跟踪文档：[README.md](README.md) 与 [MULTI_AGENT_ARCHITECTURE.md](MULTI_AGENT_ARCHITECTURE.md)。
5. 如存在 `NEXT_SESSION_HANDOFF.md`，仅把它作为临时交接线索，并用以上来源复核。

本地交接文件被 `.gitignore` 忽略，可能只存在于当前工作副本且容易过时。若文档、memory 与代码冲突，检查代码和测试，修正低优先级文档；不要为了配合旧文档改坏实现。

不要读取、输出或提交 `backend/.env`、API Key、模型凭据、完整会话 transcript 或本地游戏隐私数据。

## 目录与模块导航

- `backend/main.py`：FastAPI 入口、REST/SSE、存档回退和本地动作 API。
- `backend/dm_graph.py`：LangGraph 父图、上下文装配、阶段能力、确定性修复、提交和回滚。
- `backend/agents/`：持续 DM 私有子图、阶段能力、真实 `StructuredTool` 适配器和提交后建议投影。
- `backend/agent_tools.py`：供 Agent 调用的确定性状态工具。
- `backend/action_service.py`：不经过模型的本地确定性动作入口。
- `backend/game_logic.py`：骰子、检定、攻击、伤害、集中、先攻和遭遇规则。
- `backend/encounter_math.py`：遭遇 XP 预算与 CR 估算的纯计算层（移植自 5e.tools，见模块头部出处）。
- `backend/rules_catalog.py`：角色构筑、装备、法术和权威角色卡派生值。
- `backend/models.py`：Pydantic API 与持久化 schema。
- `backend/storage.py`：游戏、角色、怪物 JSON 及 rewind snapshot。
- `backend/rag.py`、`backend/rag_embeddings.py`：可选本地 Chroma/Qwen3 GGUF 规则检索。
- `frontend/src/App.jsx`：当前主要 React UI 和异步生命周期守卫。
- `frontend/src/api.js`：浏览器 API/SSE 客户端。
- `tests/`：后端单元、工作流和 API 契约测试。

按需查看 [.agent/memory/module-map.md](.agent/memory/module-map.md)，不要把仓库全部文件一次性载入上下文。

## 安装、启动与验证命令

在仓库根目录执行，除非命令另有说明。

```powershell
# 一键启动后端和前端；脚本会选择端口并写入本地 runtime-logs
.\start.cmd

# 后端依赖
python -m pip install -r backend/requirements.txt

# 后端测试
python -m unittest discover -s tests -v

# 前端依赖、开发、构建、Lint
Set-Location frontend
npm install
npm run dev
npm run build
npm run lint

# 仓库补充检查
git diff --check
```

当前没有仓库定义的格式化、静态类型检查、数据库迁移或代码生成命令；不要虚构等价门禁。更完整的命令依据和已验证状态见 [.agent/memory/commands.md](.agent/memory/commands.md)。

## 关键工程约束

- `GameState` 是权威状态；模型不得直接写存档或构造未结算事实。
- 状态变化必须经过已注册、当前阶段允许且属于当前 Agent 的真实工具。
- 成功工具才可改变状态；失败工具必须保持输入状态不变。
- DM 的多个写工具调用必须串行，避免从同一旧状态并发覆盖。
- 战斗中必须遵守当前行动者以及 action、bonus action、reaction 槽位。
- DM 控制的行动者必须结算或明确放弃动作，并推进回合；不能只用叙事跳过。
- 校验修复使用受限工具，不在 validator 中隐藏修改业务事实。
- `finalize_turn` 是主回合唯一提交点；失败回合恢复初始快照。
- 行动建议是提交后的非事务投影，不得影响主回合成功与否；敌方回合不显示玩家建议。
- 删除和重写消息依赖完整 rewind snapshot，不做仅聊天记录的表面删除。
- `risk_level` 只描述内部校验、事务和回滚要求，不自动触发玩家确认；只有缺少明确意图且真正涉及玩家决定权的分叉才通过 LangGraph interrupt 请求具体选择。
- interrupt 暂停结果不得发布 staged state；取消、失败或 checkpoint 丢失都必须恢复初始快照，checkpoint 不等同于剧情分支。
- 前端以服务端 snapshot、action options 和版本守卫为准，不在浏览器复制规则结算。
- 标准怪物目录当前是只读资产；游戏内新怪物写入 `GameState.monster_templates`。
- `backend/Game/`、`backend/Characters/`、`backend/Knowledge/`、`backend/Documents/` 和 runtime log 属于本地数据或生成资产，遵守 `.gitignore`。
- 修改 schema、API、工具契约或 Agent 工具所有权时，联动检查后端、前端 API、工具注册和测试。

## 中文注释规范

在跨功能交互、内部自有设计、非显然约束、状态机、回滚、并发/循环防护和关键规则处添加必要的简体中文注释，重点说明“为什么”。不要给直观代码逐行翻译，也不要用注释代替测试和清晰命名。

## 完成任务的验证标准

按风险选择验证，但涉及产品代码时至少：

1. 运行相关目标测试；跨模块或规则变更运行完整 `unittest`。
2. 前端行为或 API 客户端变更运行 `npm run build` 与 `npm run lint`。
3. 运行 `git diff --check`。
4. 检查 `git status --short`，确认没有覆盖会话开始前的用户修改。
5. 涉及真实模型、浏览器、SSE 或本地 GGUF 的行为若未实测，明确标记“未验证”，不能用单元测试替代说明。

## 本地记忆读取协议

开始非简单任务前：

1. 先读取当前作用域的 `AGENTS.md`。
2. 根据任务只读取相关的 `.agent/memory/*.md`；不要盲目加载所有 memory 文件。
3. 查找 `.agent/tasks/` 中相关且状态为 active/进行中的 ExecPlan。
4. 必要时再打开权威设计文档和代码验证事实。

推荐路由：

- 项目目标/范围：`project-brief.md`
- 数据流/边界：`architecture-map.md`
- 修改联动：`module-map.md`
- 命令：`commands.md`
- 工程规则：`conventions.md`
- 历史坑点：`common-pitfalls.md`
- 术语：`terminology.md`

代码、测试、配置和已接受 ADR 优先于 memory。memory 与代码冲突时，先检查代码，再最小修正文档。

普通实现细节、聊天流水账和每次提交摘要不要进入长期记忆。只有形成长期有效的新事实时才更新 memory。

## ExecPlan 协议

复杂、跨模块、多阶段、需要多次验证或可能跨会话的任务，应创建或继续：

```text
.agent/tasks/YYYY-MM-DD-<task-name>.md
```

遵循 [.agent/PLANS.md](.agent/PLANS.md)。工作过程中持续更新 Progress、Decisions、Discoveries、Validation、Remaining work 和 Resume instructions；不要等到会话末尾才补写。简单修复无需 ExecPlan。

## 任务结束时的记忆维护

- 先更新当前 ExecPlan 的真实进度和验证结果。
- 仅当变化形成长期有效的新事实时，最小更新对应 memory。
- 只有稳定项目入口、命令或全局工程规则变化时才修改本文件。
- 只有重大、长期有效且存在替代方案的技术决策才创建 ADR。
- 不记录密钥、完整 diff、完整 transcript、临时故障日志或尚未确认的推测。

## ADR 边界

ADR 位于 `docs/adr/`。适合记录持久化方式、模块边界、外部依赖、协议、不可逆迁移等长期决策；普通库调用、局部重构和易撤销实现选择不要滥建 ADR。模板见 [0000-template.md](docs/adr/0000-template.md)。

## Codex hooks

项目级配置在 `.codex/hooks.json`，实现位于 `.codex/hooks/`：

- `SessionStart` 在启动/清空时建立 Git 基线，在恢复/压缩时沿用基线，并提醒按需读取记忆。
- `PostToolUse` 只做确定性变化观察，不调用 AI、不修改文档。
- `Stop` 对高信号变化打开一次记忆维护 continuation。
- 临时状态优先写入 `git rev-parse --git-path codex-memory-hook`；若 Git 目录在沙箱中只读，则降级到按 worktree 路径哈希隔离的系统临时目录，不进入工作树。
- `stop_hook_active` 和已审计 diff 指纹共同阻止无限循环。

Hook 是维护提醒和增量校准机制，不是完整正确性边界。Hook 触发后，AI 可以判断“无需更新长期记忆”，不得为了满足 hook 机械修改文档。Hook 不递归执行 `codex exec`，也不调用外部 LLM。

项目 hook 新增或变化后，用户需要在 Codex CLI 使用 `/hooks` 审查并信任其当前哈希。

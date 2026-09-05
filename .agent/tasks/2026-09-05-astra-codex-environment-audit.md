# Astra Codex 环境与项目指导审计

Status: completed
Updated: 2026-09-05

## Goal

依据当前 OpenAI 官方文档升级本机 Codex 的 Astra 支持，按需要安装技能，并审查与修正项目 AGENTS.md、Hooks 和相关记忆协议。

## User-visible outcome

后续任务使用兼容 Astra 的 Codex 环境；项目指导与 Hook 行为有可复核的来源、测试和明确的生效条件。

## Scope / Non-goals

- In scope：Codex CLI、本机相关模型配置、必要技能、项目指导和 Hook 实现与测试。
- Non-goal：DM 游戏模型档案、凭据、玩家存档、产品功能、提交、正在运行的桌面应用重启。

## Relevant context and files

- `AGENTS.md`、`.agent/PLANS.md`、`.agent/memory/conventions.md`。
- `.codex/hooks.json`、`.codex/memory-policy.json`、`.codex/hooks/`。
- 用户级 Codex 配置只输出允许的非敏感字段；不读取认证文件或完整 transcript。
- 会话初始修改：common-pitfalls.md、module-map.md、App.jsx、retryUi.js、retryUi.test.mjs；保留原有改动。

## Progress

- [x] 读取项目协议，检查 Git 基线与相关既有审计。
- [x] 查询并读取 OpenAI Hooks、AGENTS.md、skills 官方文档。
- [x] 确認 PATH 上的 CLI 为 0.147.0；全局模型已经是 gpt-6-astra / xhigh。
- [x] 核对最新稳定 CLI、Astra 模型默认配置并升级至 0.153.4。
- [x] 审查 Hook 实现与指导冲突，修复三项缺陷、补齐策略和指导。
- [x] 安装官方 playwright 与 security-best-practices，保留已有 openai-docs、langgraph-docs。
- [x] 执行目标测试、配置验证、Git 差异检查并记录生效条件。

## Decisions

- 2026-09-05：保留用户明确选择的 Astra；不将产品 DM provider 一并迁移。
- 2026-09-05：以实际 fetch 的发布文档为准；文档搜索索引目前落后于 changelog 页面，后者已经发布 0.153.4。
- 2026-09-05：不自行填写 Hook trust 哈希，也不通过旁路标志跳过用户的 Hook 信任审查。
- 2026-09-05：保留 Astra / xhigh，移除全局 context window / auto-compaction 覆盖，采用当前模型目录默认值；未改权限、现有 Hook 开关、MCP 凭据或游戏 provider。
- 2026-09-05：用户配置已将三个项目 Hooks 禁用，保留此既有选择。项目本身处于 trusted 状态，不能把它误报为 Hook 已启用。
- 2026-09-05：个人技能采用当前官方文档的 `.agents/skills` 目录；不复制已有系统技能，避免同名技能重复出现。

## Discoveries / surprises

- 用户配置原有全局 1,000,000 token 上下文与 900,000 自动压缩覆盖；已移除覆盖，未把 API 最大上下文直接写回 Codex 配置。
- `features.js_repl` 已被本机 CLI 标为 removed，已移除这个无效关闭项。
- conventions.md 的风险级别自动确认说明与根 AGENTS.md、`backend/agents/tool_adapters.py` 当前分支冲突，已最小修正。
- 官方文档搜索可用；changelog Markdown 抓取返回 404，HTML 页面可读。
- 桌面应用附带的独立 CLI 为 0.153.3；npm 升级只更新 PATH 上的 CLI，没有替换正在运行的桌面应用组件。
- Hook 原实现到生成证据时才排除 ignored 文件，导致它们提前被读入哈希，而且文档变化会改变去重指纹。现已在内容读取前过滤，旧基线中的忽略路径也跳过。
- Hook 的 `mkdir(exist_ok=True)` 未验证已有目录可写，导致只读会话目录不走 fallback。现增加短暂写入探针。
- 官方仍将 unified exec 匹配为 `Bash`，code mode 对嵌套工具调用应用 Hook；现有 matcher 不需改成 `exec_command`。
- 四份历史计划缺少 `Status:`。三份按原有“已完成”统一元数据；设计方向 D 计划保留 active，并明确历史浏览器验证尚未完成。此举没有重新验证历史产品变更。
- 首次测试在 Windows 沙箱短路径临时目录处报 PermissionError；正常权限运行成功。首次 Playwright 总帮助输出完成后 npx 退出断言，随后版本和 open 子命令帮助均正常退出；未做浏览器交互验收。

## Validation

- [x] 原始 Hook 25 项 unittest 成功。
- [x] 在原始实现上运行新增缺陷回归，三项均按预期失败。
- [x] `python -m unittest discover -s .codex/hooks/tests -q`：修复后 30 项成功（项目 Python，正常本机权限）。
- [x] `codex --version`：0.153.4。
- [x] `codex app-server --strict-config --stdio` 初始化成功；`model/list` 返回 gpt-6-astra、hidden=false、isDefault=true，且支持 xhigh。
- [x] `skills/list` 强制刷新发现两个新增用户技能与已有系统 openai-docs / 用户 langgraph-docs；错误数为 0。
- [x] Playwright CLI `--version` 返回 0.1.19；`--help open` 成功。Windows 可直接使用 `npx --yes --package @playwright/cli playwright-cli ...`，无需照抄 POSIX shell wrapper 的安装路径。
- [x] `git diff --check` 成功，只有仓库既有 LF/CRLF 提示。
- [x] 游戏后端 health=ok，前端 HTTP 200；没有读取玩家存档或调用游戏模型。
- 未运行：产品后端全量测试、前端 build/lint（本次没有修改产品代码）；真实模型调用、Hook 启用后的真实生命周期、浏览器交互均未验证。

## Audit outcome and sources

| 项目 | 结果 |
| --- | --- |
| CLI / Astra | 从 0.147.0 升级到官方当前稳定 0.153.4，模型目录已识别 Astra。依据：[更新日志](https://learn.chatgpt.com/docs/changelog)。 |
| 模型配置 | 保留用户推理偏好，恢复目录提供的上下文/压缩默认值。依据：[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)、[Astra 模型页](https://developers.openai.com/api/docs/models/gpt-6-astra)。API 模型页与 Codex picker 的能力应分别核对。 |
| AGENTS.md | 现有结构、按需记忆、项目约束符合指南，大小低于默认 32 KiB；补充事实优先级与指令优先级的区别、技能发现目录和 Code Review Rules。依据：[AGENTS.md 指南](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。 |
| Hooks 协议 | 现有事件、Windows override、Git 根路径、Stop JSON 和循环防护协议符合发布文档；修复的是本项目实现缺陷。依据：[Hooks 发布行为](https://learn.chatgpt.com/docs/hooks)。 |
| Hook 策略 | 增加 `.agents/**`、环境文件排除以及 `start.sh` 高信号识别。保持三个既有事件，不额外添加无用途的生命周期处理器。 |
| 技能 | 官方库两个技能装入用户 `.agents/skills`，app-server 实际发现成功；无需所谓 Astra 专用技能包。依据：[Build skills](https://learn.chatgpt.com/docs/build-skills)。 |
| 内置记忆 | 保留 Accepted ADR 的仓库文档方案；官方没有要求替换为另一套自动记忆服务。 |

用户配置原文件已备份在其原目录的 `config.toml.before-astra-audit-20260905-104017.bak`。备份不进入仓库，不输出完整配置。

## Remaining work

- 本次审计与修改已完成。
- 若用户希望恢复自动 Hooks：在项目目录启动 Codex CLI，执行 `/hooks`，逐项检查并启用/信任；这是官方信任流程，不由脚本写哈希代替。
- 新的 CLI 调用使用 0.153.4；技能可在下一轮任务使用。桌面应用自身更新通过应用更新机制处理，本次没有重启它。
- 历史设计计划的浏览器验收属于原设计任务，恢复该任务时先复核是否仍适用。

## Resume instructions

1. 先核对本计划和 Git 状态；不要覆盖初始用户修改。
2. 升级时重新核对官方 changelog 与实际 CLI；本计划记录的是 2026-09-05 的验证快照。
3. 需要启用 Hooks 时先检查用户当前开关和 `/hooks` 状态；不要把源码测试通过误认为真实 Hook 已运行。

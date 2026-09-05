# 主持过程真实流式输出与回合骰点记录

Status: completed
Updated: 2026-09-05

## Goal

修复主持过程文本只能整块出现的问题；在每轮主持回复上方增加默认折叠的骰点记录，包含用户明确要求的暗骰和明骰。

## User-visible outcome

主持公开过程文本随真实上游增量出现；骰点框能查看本轮每次掷骰的原始骰值、总值、用途、明暗标记及提交状态，刷新后仍属于正确回复。

## Scope / Non-goals

- In scope：Codex 模型传输、SSE、掷骰观察与消息持久化、前端折叠卡、回归与合成/真实流式验证。
- Non-goal：暴露模型私有推理、读取真实玩家存档/凭据、修改骰点或规则结果、替换游戏模型档案、Git 提交。

## Relevant context and files

- `backend/model_backends.py`、`dm_graph.py`、`main.py`、`turn_stream.py`。
- `game_logic.py`、`ability_scores.py`、`agents/tool_adapters.py`、`models.py`、`player_projection.py`。
- `frontend/src/App.jsx`、`api.js`、相关测试与 `.agent/memory/common-pitfalls.md`。
- 保留已有未提交的修复、Hook、文档和前端变化。

## Progress

- [x] 核对相关历史计划、当前代码、已脱敏运行时 provider 与 CLI 版本。
- [x] 查阅官方 app-server 增量事件与输出 schema 文档。
- [x] 验证可隔离的真实增量传输并接入模型适配器；新回合、重试和重写共用 SSE。
- [x] 在实际掷骰处采集记录，绑定回复并支持暂停/恢复/失败。
- [x] 实现默认折叠卡与实时过程展示。
- [x] 完成回归、真实合成模型流式 smoke、前端构建和浏览器验证。

## Decisions

- 2026-09-05：用户的新要求覆盖此前“所有暗骰都从玩家响应过滤”的展示策略；仅通过专用骰点记录提供有意展开的明暗骰结果，不混入普通剧情正文。
- 2026-09-05：输出的是模型公开正文增量和工具观察，不读取或展示私有推理。
- 2026-09-05：骰点在确定性执行处采集，避免漏掉嵌套检定与自动先攻；记录只做观察，不决定事务提交。

## Discoveries / surprises

- 当前游戏 provider 为 codex-cli，模型 gpt-5.6-terra/high，CLI 为 0.153.4。
- `codex exec --json` 的旧适配器已能解析某些 delta 形状，但真正的 agentMessage 增量在 app-server 通知中。
- app-server 不能直接沿用 exec 的 `--ignore-user-config` 全局参数，需要核对本机协议的隔离能力。
- 安装版本拒绝 schema 文档中的 `readOnly.access`，实际使用 `sandboxPolicy={type:readOnly}`，配合临时 cwd、ephemeral、禁用宿主能力及拒绝意外工具请求。
- 现有隐私投影会过滤 visibility=hidden，新增骰点记录必须有明确且经过校验的展示出口。

## Validation

- [x] 项目 Conda 环境运行隔离入口 `.agent/audits/2026-09-05-backend/run_checks.py --baseline`：285 项，284 通过、1 项 opt-in CLI 测试跳过；包括协议隔离、真实骰点观察、嵌套骰点、失败、暂停恢复及重试/重写 SSE 回归。
- [x] 真实 Codex 合成输入：旧 exec 首尾仅 1 个正文块；app-server 收到 193 个正文 delta。仅记录计数与耗时。
- [x] 真实生产 API + Codex + 浏览器、临时合成存档：生成期间 144 次页面正文更新，2→218 字，跨度 4375ms；两条主持回复的骰点框均默认折叠，无水平溢出。明骰/暗骰展开显示已目视检查。
- [x] 浏览器刷新后两条回复仍分别记录 2 次（1 明骰、1 暗骰）和 0 次掷骰，均默认折叠；无掷骰提示正确。旧消息兼容显示未记录。
- [x] 前端 build 成功；lint 0 errors、2 条既有 Hook dependency warning；`node --test --test-isolation=none src/apiStream.test.mjs src/rollUi.test.mjs src/retryUi.test.mjs src/narrativeRollUi.test.mjs` 10 项通过。
- [x] `git diff --check` 通过，只有工作区 CRLF 提示；`git status --short` 核对保留此前修改。相关 memory 已按当前代码校准，未修改根工程规则。
- [x] 运行中的后端 23334 health=ok、OpenAPI 已包含 RollRecord 与 ChatMessage.roll_records；前端 5173 HTTP 200。隔离验收浏览器与 23581 临时服务已关闭，合成存档及临时页面快照已清理。

## Remaining work

- 本任务无剩余实现。真实玩家存档长流程、其他 provider 与可选 GGUF 不在本次实测范围。

## Resume instructions

1. 若继续流式相关调试，先看当前代码、此计划与 Git 状态，保留已有未提交工作。
2. 模型 smoke 只发送合成内容；不要读取 .env、认证文件或真实游戏内容。可用同目录审计脚本复现隔离生产 API 场景。
3. 升级 Codex 时核对 app-server 实际协议；验收完成前的多次正文更新，不以打字动画冒充流式。

# 移除自动回复选项

Status: completed
Updated: 2026-09-06

## Goal

移除主持回复及冒险开场后的自动行动建议，消除相应模型调用与缓存写入。

## User-visible outcome

玩家直接自由输入行动，不再等待或看到“行动灵感”；必要的剧情选择和确定性本地动作仍可使用。

## Scope / Non-goals

- In scope: 前端建议 UI/请求/回滚字段，后端建议 Agent/工具/API，开场建议与存档 schema，相关测试和现行文档。
- Non-goal: 修改规则结算、真实存档、模型配置或历史 ADR。

## Relevant context and files

- `backend/dm_graph.py`、`backend/main.py`：原独立建议生成链路；原 `backend/agents/suggestions.py` 已删除。
- `backend/adventure_service.py`：开场建议也属于移除范围。
- `frontend/src/App.jsx`、`frontend/src/retryUi.js`：建议请求与失败恢复。
- 现有前端设计 ExecPlan 仍 active；本任务单独维护功能移除进度。

## Progress

- [x] 读取工程约束，识别生成、缓存与 UI 链路。
- [x] 在隔离工作副本移除功能，保留必要选择。
- [x] 执行完整后端、前端检查，核对旧数据兼容性。
- [x] 同步工作区，更新现行文档并检查实际服务。

## Decisions

- 2026-09-06：彻底移除生成入口；旧存档中的建议字段由 schema 忽略，不批量改写玩家文件。
- 2026-09-06：保留 `request_player_choice` 与确定性 `action-options`，两者不属于自动回复选项。

## Discoveries / surprises

- 旧建议测试文件混有正文清理、字数和模型预算测试，必须保留这些有效回归。
- 工作区已有大量先前修复；以本任务开始时的文件哈希核对同步，保留先前修改。

## Validation

- 完整隔离 unittest：384 项，383 通过、1 项真实 CLI opt-in 跳过。
- 前端 build 通过；lint 0 errors、2 条已有 Hook warning；15 项 Node 测试通过。
- 回归验证旧建议字段被忽略、旧暂停恢复不受影响、建议 API 已无路由、确定性 action-options 仍存在。
- Chrome 合成存档验收：载入与自由输入发送后无建议区/加载提示，回合完成；保留状态栏与消息操作。使用确定性合成服务，未调用真实模型。
- 24 个源文件按本任务基线哈希检查后同步，根目录与测试副本一致；先前修改保留。
- 实际 23334 服务已重载，OpenAPI 不再有建议路由与 ChatMessage 建议字段，action-options 仍存在。
- Markdown 链接解析通过；git diff --check 通过（仅已有换行符提示）。

## Remaining work

- 无。临时验收服务与页面已关闭。

## Resume instructions

1. 先核对当前代码与本计划。
2. 隔离副本为 `output/combat-control-fix`；本任务基线为 `output/remove-suggestions-baseline`。
3. 不读取真实游戏内容或凭据，不将旧测试成功视为本次验证。

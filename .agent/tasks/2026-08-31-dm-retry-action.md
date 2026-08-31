# 主持消息一键重试

Status: completed
Updated: 2026-08-31

## Goal

在主持人消息附近提供“重试”操作，服务端从该回复前一条玩家行动对应的 rewind snapshot 恢复，并用原行动重新生成。

## User-visible outcome

- 正常主持回复可从消息操作区重新生成。
- 失败主持回复的重试操作常驻可见，不需要先找到上一条玩家消息进入编辑态。
- 点击最新回复直接重试；重试较早回复时明确提示会移除后续剧情。

## Scope / Non-goals

- In scope: retry API、前端消息状态映射、按钮和忙碌反馈、契约测试、浏览器验证。
- Non-goal: 更换模型档案、自动无限重试、保留被重试点之后的剧情分支。

## Relevant context and files

- `backend/main.py`：消息 delete/rewrite 与 rewind snapshot 入口。
- `frontend/src/App.jsx`：消息映射、生命周期守卫和消息操作区。
- `frontend/src/api.js`：浏览器 API 客户端。
- `frontend/src/index.css`：消息操作的显示与交互状态。
- `tests/test_main_streaming.py`：消息回退/重写 API 契约测试。

## Progress

- [x] 确认 retry 应由服务端根据主持消息索引解析前一条玩家行动，避免前端猜 snapshot。
- [x] 新增 retry API 与失败契约。
- [x] 接入消息操作区、忙碌态和失败态常驻显示。
- [x] 完成自动化与浏览器验证。
- [x] 后续修复：点击重试时立即移除目标主持回复及后续消息，并同步清空其思考过程和行动灵感；传输失败时恢复原 UI。

## Decisions

- 2026-08-31：任何紧邻玩家行动、且存在 rewind snapshot 的主持回复都可重试；失败回复常驻显示，正常回复沿用现有 hover/focus 操作区。
- 2026-08-31：最新主持回复一键执行；历史回复重试会移除后续剧情，前端先确认影响范围。
- 2026-08-31：失败回合不再请求行动建议投影，避免模型已经失败后又发起一次无意义模型调用。
- 2026-08-31：重试采用可恢复的前端乐观回滚；旧回复与其临时投影不能在新回复生成期间继续显示，但 HTTP/网络失败也不能让它们永久消失。

## Discoveries / surprises

- 现有 rewrite 已具备正确 snapshot 语义，但入口绑定在玩家消息且必须进入编辑态。
- `assistant_response` 时间线事件已有 `payload.turn_status`，可用于识别并常驻显示失败回复的恢复入口。

## Validation

- [x] `C:\Users\iPlayForSG\.conda\envs\DM_Agent\python.exe -m unittest tests.test_main_streaming -v`：18 项通过。
- [x] `C:\Users\iPlayForSG\.conda\envs\DM_Agent\python.exe -m unittest discover -s tests -v`：211 项通过。
- [x] `npm run build`（`frontend`）：通过。
- [x] `npm run lint`（`frontend`）：0 error；保留 2 条既有 hooks dependency warning。
- [x] `git diff --check`：通过，仅显示仓库现有 LF/CRLF 转换提醒。
- [x] 浏览器确认失败主持消息旁常驻“重试本回合”（操作区 opacity 1），3 条正常主持消息的“重试”默认隐藏（操作区 opacity 0），布局位于对应消息下方。
- [x] `node src/retryUi.test.mjs`：1 项通过，验证目标回复及后续消息、思考过程和行动灵感一起移除，并保留失败恢复快照。
- [x] 后续前端验证：`npm run build` 通过；`npm run lint` 0 error，保留 2 条既有 Hook warning。
- [x] 浏览器合成状态确认重试前目标回复、完成态思考面板和行动灵感同时存在；有删除语义的状态转换改由纯函数测试验证，临时合成存档与 rewind 已清理。

## Remaining work

- 无。由于当前 Codex CLI 已知仍在报 `handshake eof`，浏览器验收没有实际点击重试，以免再次改写本地存档；API 的回滚与原行动复用已由契约测试覆盖。

## Resume instructions

- 已完成，无需继续。

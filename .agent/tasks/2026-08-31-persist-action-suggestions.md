# 持久化主持回复的行动灵感

Status: completed
Updated: 2026-08-31

## Goal

把已经生成的行动灵感持久化到对应的主持回复，重新进入存档时直接展示，避免无操作触发重复生成。

## User-visible outcome

行动灵感生成一次后随主持回复保存；离开并重新进入游戏时直接恢复。旧存档缺少缓存时只补生成一次，成功后写入存档。

## Scope / Non-goals

- In scope：消息 schema、行动灵感投影 API 的缓存写入与并发校验、冒险开场建议、前端存档恢复、相关测试。
- Non-goal：改变 Suggestion Agent 的生成内容、把建议纳入主回合事务、修改玩家本地存档内容用于测试。

## Relevant context and files

- `backend/models.py`：`ChatMessage` 持久化结构。
- `backend/main.py`：行动灵感投影接口、冒险开场与存档保存。
- `backend/dm_graph.py`：主持回复提交时的消息构造。
- `frontend/src/App.jsx`：存档进入与投影请求生命周期。
- `tests/test_main_streaming.py`、`tests/test_action_suggestions.py`：API 与消息绑定回归。

## Progress

- [x] 确认重复生成根因是建议只存在前端内存，投影接口未保存结果。
- [x] 将建议绑定到对应 assistant 消息并持久化。
- [x] 让前端优先恢复已保存建议，不再自动重生成。
- [x] 完成后端、前端与差异验证。

## Decisions

- 2026-08-31：将 `action_suggestions` 放在 `ChatMessage`，因为产品语义是“属于这次主持回复”，而不是属于易变化的全局当前回合。
- 2026-08-31：投影仍在主回合提交后执行；缓存写入前复核 turn 和回复身份，避免迟到请求覆盖更新后的存档。

## Discoveries / surprises

- 当前 `POST /action-suggestions` 每次都重新调用 Suggestion Agent，且 `_action_suggestions_for_state` 固定返回空列表。
- 旧消息缺少新字段时会按“尚未生成”兼容加载；首次成功补生成后即写入原 assistant 消息。
- 主回合与投影请求可以交叠，因此回合保存前需要合并已经落盘的历史消息投影，避免旧快照覆盖缓存。

## Validation

- [x] `python -m unittest ...` 目标测试 — 27 项通过。
- [x] `python -m unittest discover -s tests -v` — 217 项通过。
- [x] `npm run build` — Vite 生产构建通过。
- [x] `npm run lint` — 0 error，保留原有 2 条 Hook dependency warning。
- [x] `git diff --check` 与 `git status --short --branch` — 通过，分支为 `refactor/backend-bugfix`，未出现构建产物或真实存档变化。

## Remaining work

- 无。

## Resume instructions

1. 任务已完成；后续修改行动灵感时保持“提交后生成、绑定回复、加载复用”的边界。

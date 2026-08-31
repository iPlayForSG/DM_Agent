# 角色创建界面中文化修复

Status: completed
Updated: 2026-08-30

## Goal

消除角色创建五步流程中由后端目录和前端展示兜底泄漏出的英文，确保新增种族、背景、起源专长、装备说明和计价单位均以简体中文呈现，同时保留英文规则标识作为 API 与存档中的权威值。

## User-visible outcome

玩家打开角色构筑器并走完“基础、构筑、装备、法术、总览”时，不再看到未翻译的种族、背景、专长、装备说明、`gp` 或 `DM` 文案。

## Scope / Non-goals

- In scope: `backend/library.py` 的玩家展示翻译、构筑/法术 API 展示字段、`frontend/src/App.jsx` 的创建流程展示兜底与中文文案、相关自动化测试和浏览器走查。
- Non-goal: 改写角色 schema、规则校验、存档中的英文规范值，或调整本次视觉改版样式。

## Relevant context and files

- `backend/library.py`：统一游戏术语翻译来源。
- `backend/main.py`：为目录数据递归附加 `*_display` 字段。
- `frontend/src/App.jsx`：角色创建五步流程与本地展示兜底。
- `tests/test_builder_localization.py`：构筑目录中文展示契约。

## Progress

- [x] 盘点五步创建流程的静态与动态英文来源。
- [x] 补齐目录术语和嵌套展示字段。
- [x] 修复前端兜底及残留英文文案。
- [x] 添加自动化回归测试。
- [x] 完成目标测试、前端 build/lint、diff 检查和浏览器走查。

## Decisions

- 2026-08-30：英文名称继续作为规则层和存档层规范值，只新增/消费中文 `*_display` 字段，避免改变校验与兼容性。
- 2026-08-30：前端保留当前本地词典作为旧后端/旧存档兜底，防止只有最新 API 响应才显示中文。

## Discoveries / surprises

- 目录已扩展到 10 个种族、16 个背景和 13 个起源专长，但翻译表仍停留在早期的 4/7/10，导致 17 个主选项直接显示英文。
- 自定义装备路径还会显示 `gp`、`DM`，并可能把商店物品的英文 `notes` 带进装备预览。
- 浏览器走查发现待定装备的空说明回退仍使用 `DM`；已改为“主持人”并在运行态复核。

## Validation

- [x] `python -m unittest tests.test_builder_localization -v` — 3 项通过。
- [x] `python -m unittest discover -s tests -v` — 203 项通过。
- [x] `npm run build` — 成功，288 个模块完成构建。
- [x] `npm run lint` — 0 errors；保留 2 条会话前已存在的 Hook dependency warnings。
- [x] `git diff --check` — 通过，仅有工作树既有的 LF/CRLF 提示。
- [x] 应用内浏览器走完五个创建步骤并检查可见英文 — 基础选项、职业技能、标准/自定义装备、法术与总览均为中文；控制台 0 errors；未保存测试角色。

## Remaining work

- 无。

## Resume instructions

1. 本任务已完成；后续新增构筑目录项时，先补 `backend/library.py` 翻译并运行 `tests.test_builder_localization`。
2. 不要回退同一工作树里既有的 `index.css`、`App.css` 删除及设计预览改动。

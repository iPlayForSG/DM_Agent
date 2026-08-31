# 回复长度硬约束

Status: completed
Updated: 2026-08-31

## Goal

让战役设置中的 DM 回复最小/最大可见字符数由提交前的独立纯文本 AI 后处理尽量满足；字符计数是唯一验收，不再因为文案长度问题取消已经完成的游戏回合。

## User-visible outcome

当设置为 1000–2000 字且初稿过短时，系统自动把已经结算的剧情交给无工具的独立扩写调用，玩家只看到扩写后的主持叙事；后处理失败也不再显示内部长度校验文案或回滚已完成回合。

## Scope / Non-goals

- In scope: 回合最终提交、已有长度补写器、长度验证追踪、后端回归测试、真实浏览器验证。
- Non-goal: 改动回复长度设置 UI、改变规则结算、用前端截断或填充叙事。

## Relevant context and files

- `backend/dm_graph.py`：已有长度计数和补写器，但尚未接入 `_finalize_turn`。
- `backend/prompts.py`：已把最小/最大长度写入 DM 指令。
- `tests/test_action_suggestions.py`：已有长度提示、计数、token 预算和编辑器单元测试。
- `frontend/src/App.jsx`：已正确读取和保存回复长度设置。

## Progress

- [x] 确认游戏 111 保存的是 1000–2000，可最新 DM 回复仅有 564 个可见字符。
- [x] 定位到 `_rewrite_response_to_length` 是未接入生产提交路径的死代码。
- [x] 在提交前补写并硬校验正常回合的最终叙事。
- [x] 覆盖补写成功、持续不达标回滚和失败回合跳过长度编辑。
- [x] 完成后端、前端和差异验证；浏览器真实模型调用因 Codex CLI 握手断开而未能完成。
- [x] 将长度不达标从事务失败改为独立纯文本 AI 后处理；字符计数是唯一验收，未命中只记录 warning 并继续提交。
- [x] 扩写/压缩提示词明确当前字符数、目标范围和原剧情，测试分别覆盖两种方向。
- [x] 删除玩家可见的长度失败与回合取消分支。

## Decisions

- 2026-08-31：以去除空白后的字符数沿用现有“可见字符”定义，和当前设置及测试契约保持一致。
- 2026-08-31：长度补写只能改写已结算正文，不能继续剧情、引入事实或调用工具；补写仍不达标视为事务失败并回滚。
- 2026-08-31：只约束正常完成的叙事，不强迫系统错误或失败说明凑到用户设置的叙事长度。
- 2026-08-31：用户反馈长度属于展示偏好，不应成为游戏事务失败条件；独立后处理仅用确定性可见字符数验收，未达标记录内部 warning 并保留最佳正文。
- 2026-08-31：过短正文使用“按原剧情扩写”的纯文本模型调用，过长正文使用压缩；都不绑定工具，也不经过 Agent 规则校验。

## Discoveries / surprises

- 设置保存、提示词传递和补写器本身都已存在；缺陷是补写器没有任何生产调用点。
- 浏览器用同一行动重写两次，均在 DM 初始模型调用阶段因 Codex CLI `handshake eof` 失败，未进入长度补写节点；失败事务保持了权威状态未提交，但当前存档显示该行动的模型不可用说明。

## Validation

- [x] `C:\Users\iPlayForSG\.conda\envs\DM_Agent\python.exe -m unittest tests.test_action_suggestions -v` — 最新 25 tests passed，覆盖扩写、压缩、命中长度及连续未命中仍提交。
- [x] `C:\Users\iPlayForSG\.conda\envs\DM_Agent\python.exe -m unittest discover -s tests -v` — 最新 211 tests passed；沙箱内首次运行因系统临时目录权限产生 12 个环境错误，允许正常临时目录访问后原命令全通过。
- [x] `npm run build`（`frontend`）— 通过。
- [x] `npm run lint`（`frontend`）— 0 errors，2 个既有 Hook dependency warnings。
- [x] `git diff --check` — 通过，仅有 Git 的 LF/CRLF 提示。
- [ ] 浏览器重写当前短回复并确认实际字符数在 1000–2000 — 两次均被外部 Codex CLI 握手失败阻塞。

## Remaining work

- 外部 Codex CLI 服务恢复后，可用游戏 111 的重试按钮补一次真实 provider smoke，确认 1000–2000 字扩写输出；当前代码级修复已完成。

## Resume instructions

1. 若继续真实验证，先确认 Codex CLI 健康，再重试游戏 111 的最新玩家行动。
2. 成功后检查最后一条 assistant 正文的去空白字符数是否在 1000–2000。

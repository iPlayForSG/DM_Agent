# 后端代码审计

Status: completed
Updated: 2026-09-05

## Goal

审计后端运行时设计和可复现 bug，按影响与证据报告；本轮不直接改写产品行为。

## User-visible outcome

提供带代码位置、触发条件、实际结果、建议修复方向和验证边界的审计报告。

## Scope / Non-goals

- In scope：API/SSE、存储与 rewind、DM 图事务、工具权限、确定性规则、模型适配和检索生命周期。
- Non-goal：修改玩家存档、读取凭据或 transcript、真实付费模型调用、产品修复、提交。

## Relevant context and files

- `backend/main.py`、`storage.py`、`dm_graph.py`、`agents/`。
- `agent_tools.py`、`action_service.py`、`game_logic.py`、`rules_catalog.py`、`models.py`。
- `model_backends.py`、`agent.py`、检索模块与 `tests/`。
- 保留本轮开始时已有的环境审计、Hook、文档和前端修改。

## Progress

- [x] 读取作用域指导、相关 memory 和历史 active 计划。
- [x] 检查现有测试并建立测试基线：229 项，228 通过、1 真实 CLI 测试跳过。
- [x] 审计 API、事务和持久化边界。
- [x] 审计工具与战斗规则一致性。
- [x] 抽查模型和检索运行时设计，区分静态风险与实证缺陷。
- [x] 12 个合成场景重现缺陷，报告初稿已完成。
- [x] 最终检查报告链接、代码位置和差异，报告已交付准备。

## Decisions

- 2026-09-05：审计结论区分实证 bug、明确实现缺口和设计风险；不把旧文档描述当作当前实现。
- 2026-09-05：不创建新用户任务或委派子代理；本轮在当前任务完成。

## Discoveries / surprises

- 主回合提交未校验存档 revision；暂停 checkpoint 恢复覆盖此后本地动作的已保存变化。
- 存档在序列化前直接截断；重写/重试在模型成功前 prune 原 rewind 分支。
- 同模板怪物 ID 复用；施法后的攻击组合被动作槽及武器限定阻挡。
- 暗骰只过滤分事件；完整公开结果仍携带隐藏值。
- 临时 HP、反应、0 先攻、第一轮先攻编辑、失能条件存在确定性规则缺陷。
- 细节及复现入口见 `.agent/audits/2026-09-05-backend/`。

## Validation

- [x] 后端 unittest 基线：隔离 dotenv、玩家存储与真实语料；229 项，228 成功、1 skipped。
- [x] 合成复现：12 项全部按预期重现已知缺陷，不代表产品正确性门禁通过。
- [x] LangGraph interrupt/persistence 与 D&D 2024 官方规则核对；规则来源已写入报告。
- [x] `git diff --check` 与报告本地链接/行号检查成功。
- [x] `git diff --name-only -- backend tests` 为空；本轮只新增审计计划、报告和复现脚本，原有修改保留。
- 真实模型、真实 SSE 网络断连和完整浏览器游玩仅在确实实测时标记。

## Remaining work

- 本轮审计完成。产品修复与真实游玩验收留给后续工作，建议先处理报告中的存档一致性问题。

## Resume instructions

1. 核对本计划和现有 Git 修改，保持 backend 产品代码只读。
2. 从 `.agent/audits/2026-09-05-backend/report.md` 获取问题编号、位置和修复顺序；先将审计复现转为期望行为回归断言。
3. 复现只操作合成数据，不读取实际游戏目录或认证文件；外部模型/SSE/GGUF 未实测事项仍需独立验收。

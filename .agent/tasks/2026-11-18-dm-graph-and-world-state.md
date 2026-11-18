# 拆分回合图并接入权威世界模型

Status: active
Updated: 2026-11-18

## Goal / User-visible outcome

合入已有项目改动，保留单一 DM 回合事务，将跨回合的角色、地点、线索、时钟与任务纳入存档。玩家能在状态面板回顾已揭示的事实。

## Scope / Relevant context

本次交付为 roadmap 第一阶段。后续离线冒险准备、真实玩家模拟评估依赖世界工具契约。查看 ADR-0003、backend/dm_graph.py、agents/、models.py、player_projection.py 和前端状态页。

## Progress

- [x] 提交 92 个既有项目文件至本地 main（5d76923）。
- [x] 抽出规划、上下文、校验、策略、工具声明和图状态。保留 DMGraphRunner 入口、父图节点名称、SQLite 恢复路径。
- [ ] 记录 ADR-0005，落实世界状态、工具、DM 上下文、玩家投影和界面。
- [ ] 验证旧档、回滚、暂停隔离以及 REST/SSE 投影，完成提交。

## Decisions

- 使用本地 main 分阶段提交。output/ 含旧工作副本、测试日志和临时脚本，保留在本机。

## Discoveries

- 初始有 41 个已跟踪文件变化，另有新产品源码、数据、测试和计划。已有 evidence_records、scene_actors 及战役记忆摘要，需保留原契约。

## Validation

- 基线与拆分后各运行完整 unittest 481 项，均成功（各跳过 1 项）。核对 124 个原方法，除一处改为使用 cls 回指外，函数 AST 一致。
- 基线前端构建、28 项 Node 测试通过，lint 0 错误、2 条既有 Hook 警告。基线工作树与暂存区 diff --check 通过。

## Remaining work / Resume instructions

先检查 Git 历史与本计划进度，按顺序验证每阶段。未来离线准备仅生成提案，采用的事实继续通过确定性工具提交。

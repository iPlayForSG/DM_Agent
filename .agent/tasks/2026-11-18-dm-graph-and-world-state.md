# 拆分回合图并接入权威世界模型

Status: completed
Updated: 2026-11-19

## Goal / User-visible outcome

合入已有项目改动，保留单一 DM 回合事务，将跨回合的角色、地点、线索、时钟与任务纳入存档。玩家能在状态面板回顾已揭示的事实。

## Scope / Relevant context

本次交付为 roadmap 第一阶段。后续离线冒险准备、真实玩家模拟评估依赖世界工具契约。查看 ADR-0003、backend/dm_graph.py、agents/、models.py、player_projection.py 和前端状态页。

## Progress

- [x] 提交 92 个既有项目文件至本地 main（5d76923）。
- [x] 抽出规划、上下文、校验、策略、工具声明和图状态。保留 DMGraphRunner 入口、父图节点名称、SQLite 恢复路径。
- [x] 在拆分提交 a849a3e 之后采用 ADR-0005。schema v5、六类事实、四个工具、DM 私有提示与玩家见闻已接入完整回合。
- [x] 验证旧档、回滚、暂停隔离、HTTP/SSE、浏览器与真实模型，完成本阶段交付。

## Decisions

- 使用本地 main 分阶段提交。output/ 含旧工作副本、测试日志和临时脚本，保留在本机。
- 单一工具可以定义不同类型的事实。时钟推进和揭示见闻分别使用独立工具，前端只消费完整快照。对话工具上限从 1 调至 3，允许同一次会面查询、更新并揭示，普通对话可直接回答。

## Discoveries

- 初始有 41 个已跟踪文件变化，另有新产品源码、数据、测试和计划。已有 evidence_records、scene_actors 及战役记忆摘要，需保留原契约。
- 工作区未找到用户提到的路线图原文件，本阶段按用户提供的推进顺序实施。

## Validation

- 基线与拆分后各运行完整 unittest 481 项，均成功（各跳过 1 项）。核对 124 个原方法，除一处改为使用 cls 回指外，函数 AST 一致。
- 基线前端构建、28 项 Node 测试通过，lint 0 错误、2 条既有 Hook 警告。基线工作树与暂存区 diff --check 通过。
- 最终全量 unittest 486 项（485 通过，1 跳过）。世界用例覆盖六类实体、旧档默认值、引用、重试、私有别名、失败回滚、取消、REST/SSE、trace、存档重载和消息 rewind。
- 前端 build、28 项 Node 测试通过，lint 0 错误、2 条既有警告。Playwright 在临时合成存档和实际本地 HTTP 服务上验证时间线见闻、发起 SSE 回合并观察见闻更新。
- 独立真实 Codex CLI（gpt-5.6-terra / low）冒烟，两步均完成：第一步从已揭示内容答出渡船时限，第二步在明确触发事件后调用 advance_world_clock，由 0 到 1。两次回复均未命中私有姓名、动机原文和内部 ID。未验证长战役一致性或本地 GGUF。

## Remaining work / Resume instructions

本阶段完成。下一阶段为离线冒险准备 Agent：从选定冒险生成结构化私有提案，章节结束后读已提交状态修订，主回合采用时复用世界工具。之后为多风格模拟玩家和多回合真实模型评估建立独立计划，复用现有的 backend/utils 评估入口。议程、长期记忆扩展、休息与升级、怪物战术留待后续阶段。

# ADR-0005 战役世界事实与玩家见闻

Status: Accepted
Date: 2026-11-18

## Context

旧档已有场景战斗员、队伍证据和章节记录。DM 还需要记住 NPC 的动机、尚待发现的线索和随事件推进的反派计划。一次调查可能只揭示秘密的一角，且该回合可能在结算中暂停或回滚。

## Decision

- 在 `GameState.world.entries` 按战役内稳定 ID 保存条目。事实按 `kind` 区分 NPC、地点、秘密、线索、时钟和任务。关联使用同一世界内的 ID。NPC 可引用既有规则行动者，线索可引用已入账的队伍证据。
- DM 通过 `record_world_entry` 写入完整事实定义和依据，通过 `advance_world_clock` 按预期旧刻度和事件依据前进，通过 `reveal_world_entry` 记录玩家当前可知的标题与摘要。`lookup_world_entry` 为只读查询。工具服从阶段授权、串行执行和回合提交。修改私有定义保留先前发布的见闻。
- 私有世界、依据、关系和内部 ID 保存在主档及 rewind 中。REST 和 SSE 的完整快照只从已发布见闻构建 `known_world`。玩家侧的增量和 trace 省略私有世界补丁，工具收据使用隐藏标记。DM 的提示按预算提供当前相关事实，并可按 ID 或名称查询。
- schema v5 对旧档使用空世界，保留原 evidence、scene actors 与章节。离线准备 Agent 后续只返回待采用的提案，主回合中的写入仍经工具及 finalize_turn。

## Alternatives considered

- 单独维护世界数据库需要与 JSON 存档、checkpoint、rewind 协调提交。
- 单个公开布尔值会在揭示姓名时一并公开背景或动机。独立见闻支持局部披露及后续补充。
- 从历史文本自动推导权威事实会把猜测纳入旧档。仅工具确认的事实进入世界。

## Consequences

完整世界随存档与快照增长。玩家笔记和 DM 内部事实可能有意不同。DM 需要在虚构世界中发生可观察变化时显式更新见闻，时钟在有依据的推进调用时增加。

## Validation / follow-up

验证旧档读取、跨回合检索、工具类型及引用、重复推进、暂停取消、重写回滚和公开出口。后续用虚构战役评估模型的主动推进与秘密叙事披露行为。

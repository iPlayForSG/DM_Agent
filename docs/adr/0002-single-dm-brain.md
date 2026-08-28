# ADR-0002：实时回合采用单一 DM Brain

Status: Accepted
Date: 2026-08-28

## Context

原实时回合依次调用 Director、Rules、阶段 Specialist、Auditor 和 Narrator。Director 的选择最终仍被权威 phase 覆盖，Auditor 需要另一次模型判断，Narrator 又会在审计后改写最终文本。该流水线增加延迟、上下文损失和人格切换，却没有加强真正的权威边界。

产品需要 DM 在规则内拥有较大叙事自由，同时继续保证骰子、战斗、资源、持久事实和存档事务的确定性。

## Decision

- 实时玩家回合只使用一个持续身份的 DM Brain，负责判断、工具调用和最终叙事。
- phase 是能力与上下文，不是 Agent 人格；DM 拥有所有阶段能力的并集，每回合只绑定 phase 与 turn profile 允许的交集。
- 移除在线 Director、LLM Auditor、独立 Narrator、Rules Agent 和阶段 Specialist 路由。
- 规则检索和战役记忆作为确定性上下文服务进入 DM。
- 正确性由工具 guardrail、确定性状态校验、写工具串行化和 `finalize_turn` 原子提交保证；不对普通叙事运行逐回合证据审计。
- 辅助 Agent 默认只读，只有在提供新信息、上下文隔离或独立并行价值时才启动；返回 brief/artifact，由 DM 决定采用。
- interrupt 前的状态是 staged transaction；只有 `finalize_turn` 能发布权威 `GameState`。

## Alternatives considered

- 保留原多角色流水线并优化 prompts：改动较小，但不能消除重复模型往返、身份切换和 Narrator 后置改写问题。
- 只移除 Auditor：减少一次调用，但 Director 和阶段人格仍没有独立信息增量，DM 连续性问题仍在。
- 允许多个写 Agent 并行：吞吐可能提高，但会让同一 `GameState` 的写入顺序和冲突处理变得不确定，不适合回合制权威状态。

## Consequences

- 普通回合的模型调用更少，DM 人格、上下文与叙事声音更连续。
- phase policy、工具 guardrail 和 deterministic validator 成为更重要的安全边界，相关测试必须保持严格。
- 叙事质量不再由在线第二模型兜底，应通过 prompt、场景回归和离线评估改进。
- 辅助 Agent 的接入门槛更高，但角色边界和故障隔离更清晰。

## Validation / follow-up

- 运行时拓扑测试只允许 `dm` 与提交后的 `suggestions` 投影。
- 工作流测试覆盖阶段工具收窄、写工具串行、确定性修复、原子回滚、高风险确认和 checkpoint 恢复。
- characterization test 证明普通 DM 叙事不会被证据启发式二次重试。
- interrupt test 证明 pending 结果不发布 staged state；checkpoint 丢失测试证明不会重放“确认”。
- 真实 provider 的连续多回合人格与延迟仍需单独 smoke test。

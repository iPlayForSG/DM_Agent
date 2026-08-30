# Architecture Decision Records

此目录记录 DM_Agent 重大、长期有效且存在真实替代方案的架构决策。

## 编号与状态

- 文件名：`NNNN-short-title.md`，编号递增且不复用。
- 状态：`Proposed`、`Accepted`、`Superseded`、`Deprecated` 或 `Rejected`。
- 新决定从 [0000-template.md](0000-template.md) 复制；不要修改模板表达某次决定。
- 替代旧决定时，新 ADR 应链接旧 ADR，旧 ADR 标记 `Superseded by ADR-NNNN`。

代码和测试是实现事实；Accepted ADR 解释“为什么采用此长期边界”。局部重构、临时 workaround、库的小版本升级和普通实现选择不需要 ADR。

## 索引

- [ADR-0001：项目级 AI 记忆采用仓库文档与确定性 Hooks](0001-project-ai-memory-system.md) — Accepted
- [ADR-0002：模型传输可选择 API 或 Coding Agent CLI，规则检索默认使用词法索引](0002-model-transports-and-lexical-rag-fallback.md) — Accepted
- [ADR-0003：实时回合采用单一 DM Brain](0003-single-dm-brain.md) — Accepted

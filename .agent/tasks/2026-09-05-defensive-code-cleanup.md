# 清理过度防御与无效兜底

Status: completed
Updated: 2026-09-05

## Goal

在用户指定的 main 分支梳理并删除没有实际契约依据的防御代码、重复校验和掩盖内部错误的兜底。

## User-visible outcome

内部实现更直接，错误不再被伪装成正常缺省结果；游戏状态、回滚和前端异步保护保持有效。

## Scope / Non-goals

- In scope: 后端核心、工具与 API 投影，以及前端客户端的候选检查；以调用链和测试确定实际删除范围。
- Non-goal: 不更改游戏规则、持久化格式和事务边界，不读取私有存档或凭据，不操作初始未跟踪 output/，不自动提交或推送。

## Relevant context and files

- AGENTS.md、architecture-map.md、common-pitfalls.md、commands.md 已读取。
- 历史 active 计划是游戏回归、工具覆盖与前端设计，不覆盖本次清理。
- backend/models.py 是类型契约，backend/requirements.txt 是依赖契约。

## Progress

- [x] 检查基线并切换 main；初始仅有未跟踪 output/。
- [x] 扫描异常捕获、动态字段兜底和兼容分支。
- [x] 核对候选调用链，落实核心依赖、类型化投影、规则槽位和异常边界清理。
- [x] 目标与完整测试、diff 审查及维护记录。

## Decisions

- 仅删除可由当前类型、注册或依赖契约证明无效的保护；外部输入校验、真实可选依赖降级、事务回滚和观察通道隔离需保留。
- LangGraph/LangChain/requests 均为 requirements 必需依赖；子 Agent 已直接导入 LangGraph，移除父图假可选分支及配套测试跳过。API backend 字段仍返回 langgraph。
- 图恢复必须直接读取真实 compiled graph 的 checkpoint；去掉通过 hasattr/callable 跳过基线核对的路径。
- 存储仅捕获文件读取、文本/JSON 解码及 Pydantic 验证异常，内部 RuntimeError 等必须向上报告。
- SSE 类型化投影仍通过 model_dump(mode="json") 序列化任意 payload，清理不改变其 JSON 转换语义。
- 本次是既有契约下的实现清理，没有新的长期架构决策，不修改 memory/ADR/AGENTS。

## Discoveries / surprises

- 必填模型字段仍有 getattr 默认值；部分内部类型化投影同时兼容任意字典。
- feature_definition_for 对未知特性本身返回空字典，不需要调用层吞掉所有异常再默认行动消耗。
- 前端的重试快照/版本守卫、外部 SSE 解析和旧消息缺省有实际恢复/兼容用途，本次不改。
- 初次完整测试在沙箱因 Windows 临时目录权限出现 57 个错误；已申请工具提升权限重跑，没有将其记为产品回归。

## Validation

- [x] 完整后端 unittest discover -s tests -q：最终 320 项，319 通过、1 项可选真实 CLI 测试跳过；包含 4 项新增契约回归。
- [x] 已覆盖存档损坏降级、内部异常透传、缺失/漂移 checkpoint、安全暂停恢复、行动槽、回复长度、建议投影与 SSE API 契约。
- [x] git diff --check 通过；最终 main 仅有本次 6 个后端文件、2 个测试文件和本计划的改动，初始 output/ 保留。
- 未改前端，未运行 build/lint；真实模型、浏览器、网络 SSE 和本地 GGUF 未验证。

## Remaining work

- 无；改动留在 main 工作区，未提交或推送。

## Resume instructions

1. 本次已完成。若继续清理，从 main 的现有 diff 开始，保留 output/。
2. 继续区分真正的外部输入降级和内部错误遮蔽，不删事务/回滚/异步版本守卫。

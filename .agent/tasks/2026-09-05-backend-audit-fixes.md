# 修复后端审计中的 11 项问题

> 后续授权：用户随后确认处理 F12，已在 [暂停写入保护计划](2026-09-05-pending-turn-write-guard.md) 中完成。下文“暂不处理”仅记录本计划当时的范围。

Status: completed
Updated: 2026-09-05

## Goal

修复审计 F01–F11，保留用户明确暂不处理的 F12（暂停期间本地动作与 checkpoint 恢复语义）。

## User-visible outcome

并发请求不覆盖较新存档，保存/重写失败保留原数据；怪物增援、法术攻击、临时 HP、反应、先攻和失能结算正确；公开响应不包含暗骰结果。

## Scope / Non-goals

- In scope：后端代码、相关 API/工具 schema 与前端客户端兼容、回归测试和必要文档。
- Non-goal：F12 的行为修改、真实玩家存档改写、全盘架构重写、提交/push。

## Relevant context and files

- `.agent/audits/2026-09-05-backend/report.md` 和 `repro_findings.py`。
- `backend/storage.py`、`main.py`、`models.py`、`game_logic.py`、`rules_catalog.py`、`action_service.py`、`agent_tools.py`、`tool_registry.py`、`dm_graph.py`。
- 本轮开始前的文档/Hook/前端 dirty set 保留。

## Progress

- [x] 解释剧情回退与继续暂停选择的区别，确认仅处理 F01–F11。
- [x] 修复持久化、并发提交与失败分支快照（F01/F02/F11）。
- [x] 修复怪物实例、先攻、临时 HP、失能（F03/F06/F08/F09/F10）。
- [x] 完成法术攻击与反应的共享确定性结算（F04/F07），联动前端目标/伤害类型选择。
- [x] 统一玩家可见响应投影（F05）。
- [x] 完成目标/全量测试、前端 build/lint、差异检查。

## Decisions

- 2026-09-05：回退历史剧情节点时恢复历史资源是正常行为；F12 描述的是继续暂停事务。本轮按用户要求不改变 F12。
- 2026-09-05：以审计复现为起点补期望行为测试，测试使用合成状态与隔离目录。
- 2026-09-05：使用持久化 `state_version` 与进程内/文件锁保护比较后提交；历史 rewind 显式传入当前版本，恢复资源但生成新版本。
- 2026-09-05：建议投影可以保留业务版本，但存储层限制它只能修改已有消息的建议字段。
- 2026-09-05：施法与法术攻击共用 `spell_resolution.py`；凭据绑定施法者及当前回合，攻击参数从规则目录推导，消耗后不可重放。
- 2026-09-05：`PlayerJSONResponse` 统一过滤 REST，SSE 使用同一纯投影；内部 GameState/trace 不被删改。

## Discoveries / surprises

- 审计中的先攻 0 错误在图 validator 也有同样表达式，已同步修正，避免正确排序被误判。
- 重写错误既可能抛异常也可能返回 failed TurnResult，两类都保留原分支；普通新回合的失败回复仍按既有行为记录。
- 新测试曾直接导入已有 TestCase 导致重复发现，已改成模块引用，最终统计不重复计算既有测试。
- 真实 LangGraph 内存图的施法→攻击→提交与两个独立进程争用旧版本的测试通过。
- 旧存档增加 Combatant.temp_hp 时只迁移缺字段，避免已有角色的临时 HP 因旧镜像字段缺失而触发错误。

## Validation

- [x] 隔离入口执行完整 unittest：261 项，260 通过、1 项真实 CLI 测试跳过；含新增 32 项修复回归。
- [x] 前端 build 成功；lint 0 errors、2 条既有 Hook dependency warning；UI 纯函数测试 6 项成功。
- [x] `git diff --check` 成功；保留会话前修改，新增文件仅为实现、测试及本任务记录。
- [x] 正在运行的后端 health=ok、前端 HTTP 200。
- Windows 沙箱中的 esbuild spawn EPERM 经正常本机权限重跑后构建成功。
- 真实模型、真实 SSE 网络断连与连续浏览器游玩若未运行，最终明确标记未验证。

## Remaining work

- F01–F11 已完成；F12 按用户要求保留。回退到历史剧情节点仍完整恢复历史物品；继续当前 interrupt 与 rewind 是不同路径。
- 真实模型、真实 SSE 断连、完整浏览器游玩与 GGUF 未在本轮验收；合成图/接口测试不替代这些验证。

## Resume instructions

1. 检查计划、Git diff 和最新目标测试结果，保留原有修改。
2. 后续修复以 `tests/test_backend_audit_fixes.py` 的期望行为断言为准；不要把历史审计复现脚本的旧缺陷断言当门禁。
3. F12 的最新状态与验证见后续暂停写入保护计划；不要修改玩家实际存档。

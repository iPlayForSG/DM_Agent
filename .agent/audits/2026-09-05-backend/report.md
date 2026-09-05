# 后端审计报告 · 2026-09-05

> 后续状态：F01–F11 已在同日修复，验证见 [修复计划](../../tasks/2026-09-05-backend-audit-fixes.md) 与 `tests/test_backend_audit_fixes.py`。F12 随后获得用户授权并完成，见 [暂停写入保护](../../tasks/2026-09-05-pending-turn-write-guard.md) 与 `tests/test_pending_turn_writes.py`。下文保留审计时的缺陷与行号快照；历史复现脚本不应作为修复后的正确性门禁。

本轮确认 12 项可复现问题，优先处理存档一致性与战斗结算。审计没有修改后端产品代码或玩家数据。以下 P1 表示建议优先修复的数据完整性或核心玩法问题；P2 表示明确的规则与展示缺陷。

## 验证范围

检查 API/REST/SSE、JSON 与 rewind 持久化、LangGraph 提交与 interrupt、工具注册和适配、动作/资源/战斗规则；另抽查模型传输、配置切换及 RAG 生命周期。不是对全部第三方依赖、所有法术和全部 D&D 规则的穷尽证明。

- 现有后端测试：229 项，228 项通过，1 项真实 Codex CLI 调用测试按开关跳过。
- 审计复现：12 个场景全部重现预期缺陷。其中暂停恢复使用真实 LangGraph 内存 checkpoint 和合成模型；并发测试使用真实线程等待和 API 函数。
- 未验证：真实模型、浏览器完整游玩、真实 SSE 网络断连、本地 GGUF/vector 运行；本轮未修改前端，因此没有重跑前端 build/lint。
- 审计入口禁用 dotenv，清除测试进程中的模型凭据，将游戏、角色与规则语料目录隔离到临时目录。标准规则目录仍用于真实的角色/法术解析。

复现命令（在仓库根目录，使用已安装后端依赖的 Python）：

```powershell
python .agent/audits/2026-09-05-backend/run_checks.py --baseline
python .agent/audits/2026-09-05-backend/run_checks.py
```

第二个命令断言的是“当前缺陷确实出现”，输出 `OK` 表示复现成功，不能当成产品正确性测试通过。修复时应将相应断言改为期望行为，并移入产品回归测试。

## 优先修复的问题

### F01 · P1 · 迟到的主回合覆盖已经保存的其他修改

位置：[main.py:449](../../../backend/main.py#L449)、[main.py:451](../../../backend/main.py#L451)、[main.py:461](../../../backend/main.py#L461)。

`_execute_turn_and_save` 在后台模型运行前取得快照，完成后重新加载存档却只合并 action suggestions，随后用旧快照派生的完整状态覆盖当前文件。没有覆盖全部写入口的游戏锁、revision/CAS 或删除标记检查。

复现：一个回合尚在运行，另一个请求把回复长度保存为 200–400；回合结束后设置恢复为 0–0。相同机制也覆盖聊天、战斗与删除入口，但本轮具体运行的是设置更新场景。

建议：为每个游戏建立统一事务入口，串行处理必要的写操作，并在最终提交校验服务器 revision；前端按钮禁用不能替代后端一致性检查。

### F12 · P1 · 暂停期间本地动作成功，恢复 checkpoint 后又丢失

位置：[main.py:1839](../../../backend/main.py#L1839)、[dm_graph.py:5404](../../../backend/dm_graph.py#L5404)。

本地动作入口允许修改带 `pending_turn` 的公开状态，而恢复只向旧 checkpoint 发送 `Command(resume=...)`，不合并此后存档的业务变化。与 F01 不同，这不需要两个请求同时进行。

复现：在剧情选择暂停时，使用物品成功、数量从 2 保存为 1；随后恢复选择，数量回到 2，已成功的本地动作被抹掉。

建议：暂停事务期间拒绝冲突的业务写入，或先明确取消暂停事务再执行本地动作；不要将任意外部变化直接合并进 staged state。checkpoint 是恢复执行位置，并不会自动合并外部 JSON 变化，见 [LangGraph interrupt 文档](https://docs.langchain.com/oss/python/langgraph/interrupts)。

### F02 · P1 · 保存失败会先清空原存档

位置：[storage.py:49](../../../backend/storage.py#L49)；rewind、角色和怪物写入也采用同类直接覆盖方式。

`open(path, "w")` 先截断文件，之后才序列化和写入。序列化异常、写入失败或进程中断都没有原子替换和旧文件保留措施；加载失败又返回 `None`，上层会当成找不到游戏。

复现：先写入有效存档，再在序列化阶段注入异常，旧文件从 926 字节变成 0 字节。

建议：先完成序列化，写同目录临时文件并 flush/fsync，再原子替换；保留必要备份，并区分“文件不存在”和“存档损坏”。JSON 主存档和 rewind 分支发布还需要共同的提交策略。

### F11 · P1 · 重写/重试失败仍提前删除旧分支快照

位置：[main.py:445](../../../backend/main.py#L445)、[main.py:446](../../../backend/main.py#L446)。

在新回合执行成功之前，`_execute_turn_and_save` 已经 prune 目标索引及后续 rewind 文件。模型/传输抛异常时原游戏仍保留，但旧分支的恢复能力已经被破坏。

复现：重写第一条玩家消息时注入请求异常；原助手消息还在，助手消息对应的旧 rewind snapshot 已不存在。

建议：新分支快照先暂存，成功提交新状态时再切换分支并 prune；失败路径保留原分支与全部快照。

### F03 · P1 · 同模板增援覆盖旧怪物并重置 HP

位置：[game_logic.py:627](../../../backend/game_logic.py#L627)、[game_logic.py:1315](../../../backend/game_logic.py#L1315)、[game_logic.py:1324](../../../backend/game_logic.py#L1324)。

怪物实例 ID 由 encounter ID、template ID 和本次循环 index 组成，每次生成都从 1 开始。同一场遭遇再次加入同一模板会得到相同键，覆盖旧实例。

复现：先生成一个 10 HP 怪物并打到 2 HP，再生成同模板；场上仍只有 1 个怪物，旧实例被替换为 10 HP。

建议：模板 ID 与实例 ID 分离，实例使用独立随机 ID 或遭遇内单调递增序号；增援不得修改既有实例的 HP、状态和先攻。

### F04 · P1 · 攻击型法术缺少可组合的权威攻击结算路径

位置：[agent_tools.py:1108](../../../backend/agent_tools.py#L1108)、[rules_catalog.py:463](../../../backend/rules_catalog.py#L463)、[tool_registry.py:646](../../../backend/tool_registry.py#L646)。

`cast_spell` 只处理施法可用性、法术位、专注和动作槽。施法后再调用 `attack_target` 会因动作已经消耗而失败；即便隔离动作槽问题，该工具对角色也只解析库存武器，不能解析 Fire Bolt 等法术攻击。

复现：Fire Bolt 施法返回成功，后续法术攻击被拒绝，敌人 HP 保持不变；独立解析 Fire Bolt 又报角色卡没有此武器。通用 `roll_dice` / `adjust_hp` 可以让 DM 手工拼装结果，但不能提供当前武器攻击同等级的法术属性、命中与伤害权威校验。

建议：将施法动作与其后续效果放入同一确定性结算上下文，或提供携带 cast ID 的法术攻击/豁免结算工具，避免重复收费，同时从角色与法术数据推导数值。Fire Bolt 需要法术攻击检定，见 [2024 法术规则](https://www.dndbeyond.com/sources/dnd/br-2024/spell-descriptions#FireBolt)。

## 其他已复现问题

| ID / 优先级 | 位置 | 触发与实际结果 | 建议 |
| --- | --- | --- | --- |
| F05 / P2 | [main.py:223](../../../backend/main.py#L223)、[main.py:1171](../../../backend/main.py#L1171)、[main.py:1666](../../../backend/main.py#L1666) | `tool.completed` 分事件过滤暗骰，但 `turn.completed` 的 `tool_results`、完整 GameState 和 trace 仍包含隐藏 total。复现隐藏 19 仍出现在公开结果 JSON。 | 建立统一的玩家响应投影，覆盖 REST、SSE、加载游戏和 traces；内部存储保留完整权威数据。 |
| F06 / P2 | [game_logic.py:641](../../../backend/game_logic.py#L641) | 10 HP、5 临时 HP 受到 3 伤害，结果是 7 HP、5 临时 HP；`temp_hp` 未参与伤害结算。 | 伤害先消耗临时 HP，剩余才扣真实 HP；与角色/战斗镜像、专注检定一起验证。 |
| F07 / P2 | [action_service.py:345](../../../backend/action_service.py#L345)、[tool_registry.py:413](../../../backend/tool_registry.py#L413)、[game_logic.py:434](../../../backend/game_logic.py#L434) | 敌方回合请求玩家 Shield 被当前行动者检查直接拒绝。reaction 槽还挂在当前回合上，每次切行动者重置。 | 将反应使用权绑定到反应者及其下次回合开始，允许合法触发下的非当前行动者，增加触发信息。 |
| F08 / P2 | [game_logic.py:600](../../../backend/game_logic.py#L600) | `initiative or -999` 把合法 0 当缺失值；0 与 -1 排序得到 `[-1, 0]`。 | 仅对 `None` 使用缺失值分支。 |
| F09 / P2 | [game_logic.py:1499](../../../backend/game_logic.py#L1499) | 第一轮中已消耗 action，给任一单位重新设置相同先攻值仍清空 action，并把当前行动者设为排序第一名。 | 区分初始化与战斗中编辑先攻，编辑不能重开行动槽或跳回先手。 |
| F10 / P2 | [game_logic.py:771](../../../backend/game_logic.py#L771)、[game_logic.py:406](../../../backend/game_logic.py#L406) | 增加 Incapacitated 后专注仍保留，角色通过本地动作服务实际攻击成功。条件只作为字符串保存，没有对应机械效果。 | 为关键 condition 建立集中规则派生，至少统一处理失能、行动资格和专注中断。 |

F06、F07、F10 的规则期望已对照 [2024 官方规则术语表](https://www.dndbeyond.com/sources/dnd/br-2024/rules-glossary)：临时 HP 抵挡伤害；反应可以在其他生物回合发生；失能禁止动作、附赠动作和反应，并结束专注。

## 设计层面需要调整，但本轮不扩大成未证实故障

1. **统一主回合、本地动作和分支操作的事务边界。** 当前只有建议生成使用专用锁，图内 `finalize_turn` 并不等于整个后端写入路径的唯一提交点。F01/F11/F12 是这一缺口的直接表现。
2. **让 Agent 和本地 API 共享同一动作结算服务。** `agent_tools.py` 与 `action_service.py` 都实现施法、攻击和资源处理，复制 guard、payload 与槽位逻辑。修复一边容易遗漏另一边；建议只保留输入/输出适配差异。
3. **按职责拆分 DMGraphRunner。** 当前 `dm_graph.py` 5,431 行，同时放 schema、意图、提示上下文、执行、验证、回复清洗、checkpoint 和 trace。建议先提取纯规则/投影与事务提交单元，用现有测试锁定行为，避免为了拆文件整体重写图。
4. **慢 I/O 与应用资源生命周期需要专门收敛。** `health/llm` 在 async 路由中直接同步探测，`rag/search` 也直接执行同步检索；配置切换先关闭全局 runner，再创建新 runner，缺少在途任务/暂停 checkpoint 迁移策略。CLI 超时只 kill 直接进程，Windows wrapper 子进程树、SSE 断线后的后台任务和 GGUF 并发启动值得专项验证。本轮不声称已复现这些真实外部故障。
5. **依赖安装不可复现。** `backend/requirements.txt` 未固定版本。当前测试通过对应当前环境，不保证重新安装能得到相同 LangChain/LangGraph、checkpoint 和 Pydantic 行为；应生成经过验证的锁定依赖并建立升级回归流程。

## 修复顺序

先处理 F01/F12/F02/F11，保护存档和分支；随后 F03/F04/F07，恢复稳定的战斗实体与法术/反应流程；再处理 F06/F08/F09/F10 与 F05 的统一响应投影。拆模块和依赖锁定可以随这些修复逐步进行。

后续每组修复应先把对应复现改成期望行为断言，再运行相关测试和全量后端测试；涉及响应 schema/客户端时联动前端验证。真实游玩验收仍需另外执行，不能由本报告中的合成测试代替。

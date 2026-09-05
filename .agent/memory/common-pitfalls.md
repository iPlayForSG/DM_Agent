# 常见坑点

## 事实源漂移

- `NEXT_SESSION_HANDOFF.md` 被 `.gitignore` 忽略，只是临时交接线索；其他 clone 可能没有，且内容不会自然随 commit 校准。它反复出现测试数量和 dirty set 过期的问题，读到时先用实际命令复核再采信。
- 重复的本地 API/走查文档已经移除。逐端点细节应从路由、schema、前端客户端和契约测试确认，避免维护第二套易漂移事实源。
- 默认 `python`（D:\Anaconda3）没有装 `backend/requirements.txt`，跑测试会误报 5 个 ImportError 而不是真实失败。后端验证必须用项目 Conda 环境的解释器。

## 规则与 schema 联动

- `roll_saving_throw` 已拒绝缺失目标/来源；角色法术必须提供 `source_ref` 与 `spell_name`，并从角色卡和法术库推导 DC 与豁免属性。环境或非角色效果仍使用显式 DC。
- `cast_spell` 处理可用性、法术位、专注和行动槽；攻击型法术返回 `cast_id`，后续 `attack_target` 必须使用该凭据，不能再次扣动作或套用武器数据。角色法术豁免仍须走权威解析，其他描述性效果仍按已支持的工具结算。
- 角色攻击会忽略模型提供的攻击数学并从角色卡解析；非角色攻击才允许受保护的显式攻击数据。
- 修改 `models.py` 时必须检查旧 JSON save、API request/response、前端字段和 combatant mirror。
- `create_party_character` 走的是和前端建卡同一套 `validate_character`：职业技能数量、初始装备 choice、戏法与预备法术数量都会卡。背景自带的技能不计入职业技能配额。
- 遭遇难度和 CR 估算是只读判断依据，不是结算结果；即兴敌人没有模板 CR，只能按防御面估算，`cr_source` 必须一路透传，不要当成权威数值。

## 前后端契约

- 长请求提交必须校验起始 `state_version`；重写/回退使用当前存档版本保护历史快照的提交，不能把历史版本直接当当前版本。建议缓存的免版本变更入口只允许修改已有消息的建议字段。
- 暂停的 checkpoint 不能自动吸收外部局部写入。API 与普通存储写入都阻止暂停期间修改本局状态，GET 游戏也不补写选项；继续旧暂停前比较业务基线并忽略版本/时间戳/trace/建议缓存，历史漂移时保留公开存档、终止私有事务。`action_options` 的禁用字段必须与对应 `state_version` 一起消费，避免旧响应继续锁住已结束的暂停。
- REST 和 SSE 均经 `player_projection.py` 过滤普通载荷中的暗骰；仅过滤 `tool.completed` 会漏掉完整 GameState、trace 或关联工具消息。用户明确要求的折叠骰点框是例外：只通过经 `RollRecord` 校验的 `roll_records` 提供明暗骰结果；不要为显示过滤改写内部权威状态。
- 反应记录属于各战斗员，在其自己的回合开始时恢复；先攻编辑不重开动作。旧存档只给缺少临时 HP 的战斗镜像补字段，显式不一致仍应交给校验发现。

- 前端怪物编辑仍调用 `POST /api/v1/monsters`，但后端固定返回 405，因为标准怪物库只读。不要在未决定产品边界前假定“保存成功”。
- Codex 真实正文流使用 `codex_transport.py` 的 app-server `item/agentMessage/delta`；`codex exec --json` 只有完成正文块，不能作为增量替代。新回合、重试和重写必须共用 SSE，升级传输后仍需实测完成前的多次页面更新，不以打字动画或私有 reasoning 冒充公开正文流。Claude CLI 当前仍使用完整响应回退。
- 骰点必须在实际掷骰处采集，不能只扫描最终 `ToolResult`（会漏掉自动先攻、嵌套专注检定和失败工具）。同值掷骰按独立 `record_id` 保留，暂停恢复保留原 id，结果绑定新增主持消息并区分结算状态；旧消息缺少记录时显示未记录，不能猜补骰值。
- 新回合/重试/重写 SSE 的连接和无数据等待均有 45 秒上限；服务端每 10 秒无业务事件时发心跳，收到最终提交载荷即可结束前端等待，不再依赖连接 EOF。断线仍不能证明服务端已取消，必须重新加载确认进度，不能自动重放行动。
- 整个 CLI 回合共享配置的等待预算，工具后的下一次模型调用只能使用剩余时间。修复工具轮次有独立总上限，不能通过每次 `tool_call_rounds + 1` 无限续期。
- 全部玩家与友方战斗员已倒地或进入 defeat 状态后，推进回合只会再次选中敌人；校验应要求 `end_encounter` 收尾，不再索要玩家攻击或循环敌方回合。死亡/被俘等状态仍须已有权威事实支持。
- `mcp_servers={}` 不能证明 Codex 传输已隔离。逐项读取 MCP 名称和协议类型后覆盖为禁用条目，并禁用 `code_mode_host`；验证真实 app-server 子进程没有个人 MCP/代码执行助手，不能仅断言配置字符串存在。
- 回复长度设置不能只依赖 DM 提示词；正常回合在 `finalize_turn` 提交前用去空白字符数检查，并交给无工具的独立纯文本调用扩写或压缩。长度是展示偏好，后处理未命中只能记录 warning、保留最佳正文，不能回滚已完成回合或向玩家暴露内部校验文案；系统错误说明不受叙事长度约束。
- 行动灵感仍是主回合提交后的非事务投影，但生成状态和结果持久化在对应 `ChatMessage`；加载存档必须优先恢复该缓存，不能因为前端内存为空就重新调用 Suggestion Agent。
- 主持回复重试必须由服务端根据 assistant 消息索引解析前一条玩家行动和对应 rewind snapshot；重试或提交玩家消息重写后，前端先替换/移除目标及后续消息、旧 interrupt、思考过程和行动灵感，传输失败才恢复整组 UI 投影。失败回复常驻重试入口，失败回合不要继续请求行动建议投影。
- 公开骰点的正文标记必须逐条对应成功的权威工具结果，模型只能决定它出现在相关叙事段落的位置，不能编写数值。暗骰需要同时从最终叙事、玩家时间线和玩家可见 `tool.completed` SSE 中过滤，不能只靠前端样式隐藏。
- `App.jsx` 是超过 3,000 行的单体组件；局部状态和 effect 依赖容易互相影响。当前 Lint 仍有两个 Hook dependency warning。

## 本地环境与生成内容

- 不读取或输出 `backend/.env`。模型配置 API 必须脱敏。
- 默认 `RAG_RETRIEVAL_MODE=lexical` 不会启动 `llama-server`。只有显式 vector 模式的查询才可能按需启动 `llama-server`/`llama-server.exe`，其首次调用受 GGUF 路径、CUDA/Metal/CPU、端口和启动超时影响；向量失败后会词法降级，排障要同时看 status 的 `retrieval_mode` 与 `vector_error`。
- `start.cmd`/`start.sh` 会写本地 runtime state 和 Vite env；这些不应成为 Git 变化。macOS 默认 `python3` 可能仍是 3.8，必须选择 Python 3.10+。
- 本地规则书与 `backend/data/spells.json` 均被忽略；缺文件会分别表现为 lexical/RAG 未就绪或法术/建卡测试失败，不要把它误判成算法回归。
- 规则规范化 manifest 会报告 `flattened-table-line` 与 `short-source`；原始规则书保持只读，先修本地来源再重新生成，不要在生成目录手改正文或忽略仍会污染 chunk 的长表格。
- CLI health 只验证 `--version`，不证明登录态有效；真实调用才验证认证。API 档案凭据在切换到 CLI 时会从子进程环境移除。
- SQLite checkpoint 是 interrupt 恢复设施，不是消息分支；删除/重写依赖 `_rewind` snapshot。rewind snapshot 在保存和恢复时都必须清除 `pending_turn`，否则已经消费的 thread 会复活成永远无法完成的选择卡。

## 容易漏掉的验证

- 单元测试不能替代真实 provider smoke、浏览器回归或本地 GGUF 启动测试。
- 工具 schema、DM runtime ownership 和 `PHASE_CAPABILITY_TOOL_NAMES` 三者都要检查；只注册函数并不会让 DM 在当前阶段实际获得工具。
- 普通回合没有 Director、LLM Auditor 或独立 Narrator。确定性 validator 只能要求受限工具修复或失败，失败由 `finalize_turn` 恢复 `initial_game_state`。
- interrupt 前的成功工具仍是 staged transaction；`input_required` 只能发布上次提交快照和 pending 元数据，取消、失败或 checkpoint 丢失时必须同时清空对外 `tool_results` / `state_delta`，不能只回滚 `GameState`。
- SQLite checkpointer 查不到 thread 时可能返回空 `StateSnapshot`，随后才以 `KeyError('game_state')` 失败；不要依赖异常文案识别 checkpoint 丢失，resume 前先检查 snapshot values 是否包含 `game_state`。
- 不要把 `risk_level` 或写入权威状态等同于玩家侧确认。明确指令、规则结算和 DM 记账直接执行；只有真正缺少玩家决定时才调用 `request_player_choice`，其公开 payload 只能包含剧情语义和具体选项。
- 自然语言攻击不能只靠一个固定词表：确定性词表是快速路径，未命中时由受约束模型补充意图；`hostile_attack` 必须贯穿探索到战斗的阶段刷新，直到玩家攻击产生权威工具结果。不要因初始探索 allowlist 没有 `attack_target` 就退回纯叙事。
- 若 DM 必须等待玩家在后果性选项中决定，提示词要明确要求调用 `request_player_choice`，不能允许只在普通正文里说“由你决定”，否则前端拿不到结构化选项和可恢复 interrupt。
- 跨后端 API 和前端行为修改后需要同时跑后端测试、前端 build/lint 与 `git diff --check`。

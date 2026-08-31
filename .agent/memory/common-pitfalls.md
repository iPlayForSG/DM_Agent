# 常见坑点

## 事实源漂移

- `NEXT_SESSION_HANDOFF.md` 被 `.gitignore` 忽略，只是临时交接线索；其他 clone 可能没有，且内容不会自然随 commit 校准。它反复出现测试数量和 dirty set 过期的问题，读到时先用实际命令复核再采信。
- 重复的本地 API/走查文档已经移除。逐端点细节应从路由、schema、前端客户端和契约测试确认，避免维护第二套易漂移事实源。
- 默认 `python`（D:\Anaconda3）没有装 `backend/requirements.txt`，跑测试会误报 5 个 ImportError 而不是真实失败。后端验证必须用项目 Conda 环境的解释器。

## 规则与 schema 联动

- `roll_saving_throw` 已拒绝缺失目标/来源；角色法术必须提供 `source_ref` 与 `spell_name`，并从角色卡和法术库推导 DC 与豁免属性。环境或非角色效果仍使用显式 DC。
- `cast_spell` 目前主要处理法术可用性、法术位、专注和行动槽；具体攻击、豁免和伤害仍需组合其他工具。角色法术豁免必须走上述权威解析，不能把模型给出的 DC 直接传成环境 DC。
- 角色攻击会忽略模型提供的攻击数学并从角色卡解析；非角色攻击才允许受保护的显式攻击数据。
- 修改 `models.py` 时必须检查旧 JSON save、API request/response、前端字段和 combatant mirror。
- `create_party_character` 走的是和前端建卡同一套 `validate_character`：职业技能数量、初始装备 choice、戏法与预备法术数量都会卡。背景自带的技能不计入职业技能配额。
- 遭遇难度和 CR 估算是只读判断依据，不是结算结果；即兴敌人没有模板 CR，只能按防御面估算，`cr_source` 必须一路透传，不要当成权威数值。

## 前后端契约

- 前端怪物编辑仍调用 `POST /api/v1/monsters`，但后端固定返回 405，因为标准怪物库只读。不要在未决定产品边界前假定“保存成功”。
- SSE 是回合完成后基于 trace 发送的阶段事件，不是真实 token/tool 流。
- 主回合 SSE 和 rewrite 目前没有底层 AbortController/idle timeout；生命周期守卫只阻止旧结果写回 UI，不会取消服务端工作。
- 回复长度设置不能只依赖 DM 提示词；正常回合在 `finalize_turn` 提交前用去空白字符数检查，并交给无工具的独立纯文本调用扩写或压缩。长度是展示偏好，后处理未命中只能记录 warning、保留最佳正文，不能回滚已完成回合或向玩家暴露内部校验文案；系统错误说明不受叙事长度约束。
- 主持回复重试必须由服务端根据 assistant 消息索引解析前一条玩家行动和对应 rewind snapshot；失败回复常驻重试入口，失败回合不要继续请求行动建议投影。
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
- 若 DM 必须等待玩家在后果性选项中决定，提示词要明确要求调用 `request_player_choice`，不能允许只在普通正文里说“由你决定”，否则前端拿不到结构化选项和可恢复 interrupt。
- 跨后端 API 和前端行为修改后需要同时跑后端测试、前端 build/lint 与 `git diff --check`。

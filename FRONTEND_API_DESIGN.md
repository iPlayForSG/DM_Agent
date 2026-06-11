# 前端顶层 API 设计

## 当前定位

当前前端已经具备：

1. 规则目录驱动的角色创建页
2. 初始剧本选择流程
3. 怪物模板页
4. 聊天页
5. 状态页
6. 最小战斗操作层

## 角色创建页

当前角色创建页已经支持：

1. 分步角色创建向导：基础信息 → 职业构筑 → 起始装备 → 法术选择 → 总览保存
2. 种族/物种选择
3. 背景选择
4. 自动带出起源专长，并明确提示“当前规则目录下由背景固定，不提供自由下拉”
5. 职业选择
6. 27 点购点属性分配，前端限制 8-15 并显示剩余点数
7. 职业技能选择
8. 基于职业目录限制 level 1 戏法数量
9. 基于职业目录限制 level 1 可准备法术数量
10. 基于规则目录选择起始装备包
11. 基于规则目录预览起始装备与起始金币
12. 基于规则目录预览起始职业资源
13. 基于规则目录预览起始法术位

这些预览都来自 `GET /api/v1/rules/character-builder` 返回的职业定义，不额外请求新接口。该接口现在还会返回：

1. 顶层 `equipment_shop_items`，供“自定义购买”模式列举可买装备
2. 每个职业上的 `custom_purchase_budget_gp` / `custom_purchase_option_id`
当前 spell picker 约定为：

1. 戏法区只展示 `level === 0` 的法术，并提交到 `spells.cantrips`
2. 已准备法术区只展示 `level > 0` 的法术，并提交到 `spells.prepared`
3. 保存按钮会在戏法或已准备法术数量未满足职业目录要求时禁用

起始装备选择当前约定为：

1. 职业目录通过 `starter_equipment_options` 提供可选起始包
2. 若起始包包含二级选择，前端会额外提交 `starter_choice_ids`
3. 起始包可以是 `Package A / B / C` 这类真实多分支，而不再是单一默认包
4. 某些起始包是“纯金币”方案，此时 `items` 为空但仍会落到 `gold_gp`
5. 角色创建页新增 `equipment_mode`，可在“标准套装”和“自定义购买”之间切换
6. “自定义购买”直接消费 `equipment_shop_items`，前端按 `cost_gp` / `bundle_size` 做预算展示，并把选中结果提交为 `custom_purchase_items`
7. 角色创建页支持一件“自定义待定装备”，提交为 `custom_pending_item`，只记录名称、数量、预留预算和备注，具体属性由 DM 后定
8. 角色保存时仍由后端根据所选起始包、`starter_choice_ids`、`equipment_mode`、`custom_purchase_items` 和 `custom_pending_item` 自动填充 `inventory` 和 `gold_gp`

当前已落地的二级选择组示例包括：

1. `musical_instrument`
2. `tool_or_instrument`
3. `holy_symbol`
4. `druidic_focus`

## 怪物模板页

当前怪物模板页支持：

1. 浏览模板摘要
2. 读取模板
3. 编辑最小字段
4. 保存模板

## 游戏流程

当前新游戏流程是：

1. 选择队伍
2. 创建游戏
3. 进入 `adventure_selection`
4. 选择初始剧本
5. 进入正式冒险
6. 必要时通过聊天侧栏公开入口开始遭遇、追加敌人或结束遭遇

补充约定：

1. `New Game` 里的队伍选择不是占位 UI；前端会把已选角色的 `character_id` 直接提交给 `POST /api/v1/games`
2. `POST /api/v1/games` 成功后，前端直接消费返回的 `game_state` 与 `action_options`，避免刚建局就再触发一次 `loadGame + loadActionOptions`
3. 已保存游戏的“进入游戏”和“新建游戏后的进入”现在走两条不同链路：前者仍会调用 `loadGame`，后者优先使用创建接口返回的状态快照

## 聊天页

聊天页当前显示：

1. `chat_history`
2. `timeline`
3. `encounter`
4. 最小战斗操作层

## 战斗操作层

当前已接入的本地动作：

1. 推进回合
2. 攻击
3. 施法
4. 技能检定
5. 豁免检定
6. 使用物品

这些操作全部走后端动作接口，不再依赖大模型回复。

其中攻击操作当前约定为：

1. 先选择攻击者
2. 从 `action-options.actors[].attacks` 里选择攻击项
3. 当前若已解析出攻击项，前端会锁定并自动带出 `attack_bonus`、`damage_expression`、`damage_type`
4. 若当前 actor 还没有可解析的攻击项，前端仍保留手动填写攻击字段的兜底模式
5. 当前也可直接选择 `resolution_mode`，区分普通伤害、非致命击倒和俘获导向攻击
6. 提交 `POST /api/v1/games/{game_id}/actions/attack` 时仍只发送后端定义的攻击字段，不附带前端内部用的 `attack_name`

角色创建页的施法选择当前约定为：

1. 使用职业定义中的 `starting_cantrips` 作为 level 1 戏法选择上限
2. 使用职业定义中的 `starting_prepared_spells` 作为 level 1 已准备法术选择上限
3. 战斗施法下拉会同时展示 `spells.cantrips` 和 `spells.prepared`
4. 当前保存按钮会在所需法术数量未选满时禁用

聊天侧栏的战斗控制当前约定为：

1. 通过 `action-options.encounter.current_actor_*` 显示当前行动者
2. 通过 actor 上的 `is_current_actor` 控制攻击、施法、技能和物品按钮的禁用态
3. 通过 `spells.options[].available` 和 `available_slot_levels` 提示法术位是否耗尽
4. 物品下拉会显示剩余数量，超出剩余数量时按钮禁用
5. 当前行动者若是敌方，侧栏只提供 DM 辅助装填与规则执行，不会自动替 DM 做决策
6. actor、装备、法术和怪物摘要优先消费后端返回的 `*_display` 字段，避免把英文 canonical 字段直接渲染到中文界面

## API 服务层

`frontend/src/api.js` 当前提供：

- `loadLobby`
- `loadCharacterBuilder`
- `loadSpells`
- `saveCharacter`
- `saveMonsterTemplate`
- `loadMonsterTemplate`
- `createGame`
- `loadGame`
- `loadActionOptions`
- `selectAdventure`
- `startEncounter`
- `addEncounterEnemy`
- `spawnEncounterTemplate`
- `endEncounter`
- `removeEncounterCombatant`
- `setEncounterInitiative`
- `rollEncounterInitiative`
- `submitTurn`
- `advanceTurn`
- `attackAction`
- `skillCheckAction`
- `savingThrowAction`
- `castSpellAction`
- `useItemAction`

当前 API 调用层补充约定：

1. 优先使用 `VITE_BACKEND_URL/api/v1` 直连后端；未配置时再回退到 `/api/v1`
2. 网络不可达时统一抛出中文错误，明确提示先检查启动脚本与后端状态
3. `start.cmd` 会自动写入 `frontend/.env.development.local`，因此开发态不再依赖固定 `23333` 端口；Windows 用户可以直接双击它启动前后端并打开浏览器。

## 当前阶段成果

当前前端已经能做到：

1. 创建规则上更合理的角色
2. 管理怪物模板
3. 选择初始剧本
4. 在聊天页直接做最小战斗控制
5. 从 `action-options` 自动带出攻击项、部分可选角色、法术和物品
6. 在角色创建页提前展示并选择后端保存时会自动补全的起始内容
7. 在角色创建页前移一部分 level 1 施法约束，而不是等保存时报错
8. 在聊天侧栏的施法选择中区分展示戏法和已准备法术
9. 在角色创建页切换真实起始装备分支，并在状态页展示金币
10. 在角色创建页处理起始包内的二级选择，例如乐器或工具
11. 在聊天侧栏为当前敌方行动者提供 DM 辅助操作，但不自动驱动敌方战术
12. 在 `New Game` 页面用中文明确展示“队伍角色”选择，并在建局时真正把所选角色写入新存档
13. 在首页、状态页、遭遇侧栏和怪物模板管理中优先显示中文本地化字段，而不是英文规则字段
14. 在首页与新建游戏弹窗使用响应式布局，避免桌面端右侧留白和窄弹窗问题
15. 在聊天侧栏通过公开 encounter API 进入战斗或追加敌人
16. 在聊天侧栏预览模板怪 AC/HP/CR，并支持 side / custom name / HP override / end encounter
17. 在遭遇面板直接移除非队友单位，并手动设置或重掷先攻
18. 在攻击表单中显式切换 `normal / nonlethal / capture`，并在有攻击项可选时把攻击元数据稳定同步到动作草稿
19. 在角色构筑页按后端 `*_display` 字段把背景、起源专长、职业、起始装备包与二级选项、起始装备明细、职业资源、施法属性等全部渲染为中文；对于后端不再直接提供 display 字段的职业资源名，前端补了一层 `localizeClassResource` 映射
20. 页面主滚动条由 `main-content` 承担，内部 `home-container`、`creator-container` 不再各自滚动，滑块始终贴紧浏览器最右侧
21. 角色创建器已改成真正的多步向导，不再把全部字段堆在单页上
22. 起始装备新增自定义购买与自定义待定装备，并在前端先做预算校验
23. 生命值改为前端只展示自动计算结果，不再允许手填任意 `hp_max`

## 当前仍保留的边界

当前前端还没做：

1. 更完整的角色 builder
2. 更完整的怪物模板编辑器
3. 升级模板对话框
4. 更细的战斗控制面板
5. 更细的当前行动者约束、资源耗尽反馈和动作禁用态

## 2026-05-08 Turn Streaming Contract

- 后端新增 `POST /api/v1/games/{game_id}/turns/stream`
  - 请求体与现有 `sendChatTurn` 相同：`{ message }`
  - 响应类型：`text/event-stream`
- 当前 SSE 事件顺序：
  - `turn.started`
  - `turn.completed` 或 `turn.input_required`
  - `turn.saved`
  - `turn.finished`
  - 失败时则为 `turn.error` + `turn.finished`
- 前端接入建议：
  - 第一阶段不要替换现有 `POST /turns`
  - 先把 `turns/stream` 作为可选增强链路，只用于聊天页提升体感
  - UI 最少可以先消费：
    - `turn.started`：显示“DM 思考中”
    - `turn.input_required`：立即把澄清提示作为系统消息显示
    - `turn.completed`：落正式回复与状态更新
    - `turn.error`：显示中文错误
- 现阶段不要假设：
  - 工具调用会逐条流出
  - RAG 片段会逐条流出
  - 长连接会自动心跳保活

## 2026-05-08 Trace Contract

- 后端现在会在 `TurnResult` 中附带 `turn_trace`
- 同时新增调试接口：`GET /api/v1/games/{game_id}/traces?limit=20`
- 前端接入建议：
  - 第一阶段不要把 `turn_traces` 直接塞进常规状态面板
  - 先只在开发模式或调试抽屉中展示
  - 优先显示：
    - `turn_status`
    - `phase`
    - `turn_profile`
    - `tool_results`
    - `rag_metadata`
    - `state_delta`

## 2026-05-08 LLM Health Integration

- 前端如果需要提示模型服务状态，现在可以先读取 `GET /api/v1/health` 或 `GET /api/v1/config` 里的 `llm` 字段。
- `llm` 摘要当前包含：
  - `model_name`
  - `base_url`
  - `raw_base_url`
  - `base_url_normalized`
  - `configured`
- 后端新增 `GET /api/v1/health/llm`，适合放在开发态“诊断连接”按钮后触发；它会真实探测远端模型服务并返回：
  - `ready`
  - `status_code`
  - `reason`
  - `detail`
  - `probe_url`
- 当聊天接口返回 `turn_status=failed` 且 `rag_metadata.model_error` 存在时，前端应把它当作模型服务错误展示，而不是普通剧情文本。

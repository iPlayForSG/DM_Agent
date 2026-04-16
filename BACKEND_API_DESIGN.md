# 后端顶层 API 设计

## 当前定位

当前后端已经具备：

1. 规则目录驱动的角色创建
2. 初始剧本生成与选择流程
3. 怪物模板保存与实例化
4. 最小遭遇/战斗状态
5. ADK 驱动的 DM 对话
6. 可直接调用的本地动作接口
7. 已正式接入 Agent 的本地规则检索工具

当前 RAG 运行链路约定为：

1. 优先使用持久化 Chroma 向量库
2. 若 `chromadb` 依赖不可用，则回退到基于 `rg` 的本地 markdown 词法检索
3. Agent 通过 `lookup_rules` 工具显式拉取规则片段，而不是把大段检索文本永久塞进系统提示词

## 规则目录

规则目录数据来自：

- `backend/data/character_builder_2024.json`
- `backend/rules_catalog.py`

当前规则目录已覆盖：

1. 种族/物种
2. 背景
3. 起源专长
4. 职业目录
5. 职业技能选择
6. 起始法术位
7. 起始职业资源
8. 起始装备

`GET /api/v1/rules/character-builder` 当前返回的每个职业定义也包含前端可直接消费的：

- `starting_cantrips`
- `starter_equipment_options`
- `starter_equipment`
- `resources`
- `starting_spell_slots`
- `starting_prepared_spells`

当前角色保存会自动填充：

- `save_proficiencies`
- `spells.ability`
- `spells.casting_mode`
- `spells.slots`
- `resources`
- `inventory`
- `gold_gp`
- 基础 `ac`

其中起始装备当前支持通过 `starter_option_id` 选择目录中的装备包，再由后端自动补全对应的 `inventory` 和 `gold_gp`。
`starter_equipment_options` 当前支持真实多分支包，例如 `package_a / package_b / package_c`，并允许某个分支只提供金币而不提供物品。
若某个起始包包含二级选择，则通过 `starter_choice_ids` 指定具体选项，再由后端解析成最终物品。

当前已落地的二级选择组示例包括：

- `musical_instrument`
- `tool_or_instrument`
- `holy_symbol`
- `druidic_focus`

当前 level 1 角色校验也会优先使用职业目录中的：

- `starting_cantrips`
- `starting_prepared_spells`

并要求戏法与已准备法术数量都与目录值一致，而不是旧的属性调整值推导。

## 核心数据

### Character

角色当前包含这些关键字段：

- `species`
- `background_name`
- `origin_feat`
- `starter_option_id`
- `starter_choice_ids`
- `gold_gp`
- `skill_proficiencies`
- `save_proficiencies`
- `resources`
- `spells`
- `inventory`
- `major_experiences`

其中 `spells` 当前至少包括：

- `cantrips`
- `prepared`
- `slots`
- `ability`
- `casting_mode`

### MonsterTemplate

怪物模板是长期资产层，可由 AI 保存，并在遭遇系统中实例化为敌人。

### CampaignFlowState

当前流程阶段包括：

- `character_creation`
- `party_creation`
- `adventure_selection`
- `exploration`
- `combat`
- `level_up`

### EncounterState

最小战斗状态当前包含：

- 轮次
- 当前行动者
- 先攻序列
- 战斗单位
- 战斗单位与角色/怪物模板的关联

## ADK 工具

当前 ADK 工具包括：

- `lookup_rules`
- `roll_dice`
- `adjust_hp`
- `add_status`
- `remove_status`
- `append_adventure_log`
- `add_inventory_item`
- `record_major_experience`
- `record_chapter_progress`
- `set_defeat_state`
- `set_scene`
- `set_active_character`
- `start_encounter`
- `add_enemy`
- `save_monster_template`
- `spawn_monster_from_template`
- `attack_target`
- `roll_skill_check`
- `roll_saving_throw`
- `cast_spell`
- `set_initiative`
- `roll_initiative`
- `advance_turn`
- `end_encounter`

其中 `end_encounter` 现在与公开 `POST /api/v1/games/{game_id}/encounters/end` 共用同一套遭遇总结逻辑：都会生成同样的结果摘要，并把摘要写入 `adventure_log`。
其中 `attack_target` 现在也支持非致命/俘获结果；剧情推进时可把证物、重大经历和章节收束结构化写回游戏状态。
其中 `lookup_rules` 会查询本地知识库，返回带来源路径的规则片段；当前配置下若向量库依赖不可用，会自动退回本地 markdown 词法检索。

## HTTP API

### 基础

- `GET /api/v1/health`
- `GET /api/v1/config`

### 规则目录

- `GET /api/v1/rules/character-builder`

### RAG / 知识检索

- `POST /api/v1/rag/search`

该接口主要用于手工验证当前知识库是否可检索；Agent 侧通过 `lookup_rules` 工具走同一套底层检索逻辑。

### 资料

- `GET /api/v1/library/classes`
- `GET /api/v1/library/spells/{class_name}`

其中 `GET /api/v1/library/spells/{class_name}` 会先经过 `RuleCatalog.resolve_spell_library_key()` 的兼容映射，再查询法术库，以兼容英文职业名和历史编码问题。

### 角色

- `GET /api/v1/characters`
- `POST /api/v1/characters`
- `GET /api/v1/characters/{identifier}`

### 怪物模板

- `GET /api/v1/monsters`
- `POST /api/v1/monsters`
- `GET /api/v1/monsters/{identifier}`

### 游戏流程

- `GET /api/v1/games`
- `POST /api/v1/games`
- `GET /api/v1/games/{game_id}`
- `GET /api/v1/games/{game_id}/action-options`
- `POST /api/v1/games/{game_id}/encounters/start`
- `POST /api/v1/games/{game_id}/encounters/add-enemy`
- `POST /api/v1/games/{game_id}/encounters/spawn-template`
- `POST /api/v1/games/{game_id}/encounters/end`
- `POST /api/v1/games/{game_id}/encounters/remove-combatant`
- `POST /api/v1/games/{game_id}/encounters/set-initiative`
- `POST /api/v1/games/{game_id}/encounters/roll-initiative`
- `POST /api/v1/games/{game_id}/select-adventure`
- `POST /api/v1/games/{game_id}/turns`

这些 encounter 接口会在创建或追加敌人时自动补齐遭遇状态，并默认为仍未设置先攻的参战单位自动掷先攻。
其中 `add-enemy` 与 `spawn-template` 也支持通过 `side` 控制参战阵营；`spawn-template` 额外支持 `custom_name` 与 `hp_override`。
其中 `encounters/end` 会通过 `GameLogic` 的统一总结入口结束遭遇，返回同一份结构化遭遇摘要，并把文本摘要追加到 `adventure_log`。
该接口的顶层响应当前会额外包含：
- `summary`
- `encounter_summary`

### 本地确定性动作

- `POST /api/v1/games/{game_id}/actions/advance-turn`
- `POST /api/v1/games/{game_id}/actions/attack`
- `POST /api/v1/games/{game_id}/actions/skill-check`
- `POST /api/v1/games/{game_id}/actions/saving-throw`
- `POST /api/v1/games/{game_id}/actions/cast-spell`
- `POST /api/v1/games/{game_id}/actions/use-item`

其中 `attack / skill-check / cast-spell / use-item` 在激活遭遇中会校验当前行动者，拒绝非当前回合持有者的本地动作请求。
敌方回合仍然由 DM 手动决定动作内容；本地动作接口只负责规则内执行，不提供自动敌方 AI。
其中 `attack` 当前额外支持 `resolution_mode`，可区分普通伤害、非致命击倒和俘获导向的攻击结算。

## action-options

`GET /api/v1/games/{game_id}/action-options` 当前会返回：

1. 可选角色与战斗单位引用
2. 角色的戏法、已准备法术与法术位
3. 角色的物品列表与金币
4. 角色的技能/豁免
5. 角色资源池
6. 从装备自动推导的攻击项
7. 从怪物动作文本中尽量解析出的攻击项

其中每个角色的 `spells` 当前字段为：

- `cantrips`
- `prepared`
- `slots`
- `options`

其中每个角色当前也会返回：

- `gold_gp`
- `starter_option_id`
- `is_current_actor`
- `defeat_state`

顶层 `encounter` 当前也会返回：

- `active`
- `round_number`
- `current_combatant_id`
- `current_actor_ref`
- `current_actor_name`
- `current_actor_side`

其中每个 `attacks[]` 项当前字段为：

- `name`
- `attack_bonus`
- `damage_expression`
- `damage_type`
- `source`

## 当前阶段成果

当前后端已经能做到：

1. 创建角色后自动获得职业起始资源、起始装备和起始法术位
2. 角色创建页已经可以切换真实起始装备分支并正确落库金币/物品
3. 部分起始包已经支持包内二级选择并正确解析成最终物品
4. 战斗面板能通过 `action-options` 获取并自动回填可用攻击项
5. 施法走本地合法性校验和法术位消耗
6. 初始剧本选择前禁用自由冒险输入
7. 敌方回合可以通过本地动作接口在 DM 控制下执行，同时受到当前行动者约束
8. 遭遇创建已经有公开 HTTP 入口，不再需要内部脚本强行注入敌人
9. 遭遇公开接口已经支持追加不同阵营的单位，以及在结束遭遇时生成统一结果摘要、写入 `adventure_log` 并回到 exploration
10. 遭遇公开接口已经支持移除非队友单位，以及公开的手动先攻编辑
11. 战斗状态现在会在先攻齐备时锁定真正的当前行动者，本地动作不能再越回合抢行动
12. 结构化状态现在支持证物/战利品写入 `inventory`、重大经历写入 `major_experiences`、以及章节总结落入 `campaign.completed_chapters`
13. Agent 现在可以通过 `lookup_rules` 查询本地知识库；即使未安装 `chromadb`，也可退回到基于本地 markdown 语料的检索模式

## 当前仍保留的边界

当前还没做：

1. 更完整的 2024 角色构建规则
2. 完整升级模板
3. 更细的法术、专长、职业特性校验
4. 更高质量的 RAG 召回、切片与排序
5. 更完整的战斗动作库

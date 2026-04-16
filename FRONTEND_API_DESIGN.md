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

1. 种族/物种选择
2. 背景选择
3. 自动带出起源专长
4. 职业选择
5. 职业技能选择
6. 基于职业目录限制 level 1 戏法数量
7. 基于职业目录限制 level 1 可准备法术数量
8. 基于规则目录选择起始装备包
9. 基于规则目录预览起始装备与起始金币
10. 基于规则目录预览起始职业资源
11. 基于规则目录预览起始法术位

这些预览都来自 `GET /api/v1/rules/character-builder` 返回的职业定义，不额外请求新接口。
当前 spell picker 约定为：

1. 戏法区只展示 `level === 0` 的法术，并提交到 `spells.cantrips`
2. 已准备法术区只展示 `level > 0` 的法术，并提交到 `spells.prepared`
3. 保存按钮会在戏法或已准备法术数量未满足职业目录要求时禁用

起始装备选择当前约定为：

1. 职业目录通过 `starter_equipment_options` 提供可选起始包
2. 若起始包包含二级选择，前端会额外提交 `starter_choice_ids`
3. 起始包可以是 `Package A / B / C` 这类真实多分支，而不再是单一默认包
4. 某些起始包是“纯金币”方案，此时 `items` 为空但仍会落到 `gold_gp`
5. 角色保存时仍由后端根据所选起始包和 `starter_choice_ids` 自动填充 `inventory` 和 `gold_gp`

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
12. 在聊天侧栏通过公开 encounter API 进入战斗或追加敌人
13. 在聊天侧栏预览模板怪 AC/HP/CR，并支持 side / custom name / HP override / end encounter
14. 在遭遇面板直接移除非队友单位，并手动设置或重掷先攻
15. 在攻击表单中显式切换 `normal / nonlethal / capture`，并在有攻击项可选时把攻击元数据稳定同步到动作草稿

## 当前仍保留的边界

当前前端还没做：

1. 更完整的角色 builder
2. 更完整的怪物模板编辑器
3. 升级模板对话框
4. 更细的战斗控制面板
5. 更细的当前行动者约束、资源耗尽反馈和动作禁用态

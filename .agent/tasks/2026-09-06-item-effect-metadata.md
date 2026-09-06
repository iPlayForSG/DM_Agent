# 拾取物品的规则数据与效果显示

Status: completed
Updated: 2026-09-06

## Goal

补全拾取武器的伤害骰与类型，展示治疗物品、卷轴、投掷物的规则效果，兼容已有库存。

## User-visible outcome

中文名拾取的弯刀显示当前角色的伤害表达式；物品栏与说明浮层能查看治疗量、伤害类型及使用条件。

## Scope / Non-goals

- In scope: 名称匹配、拾取工具/schema、只读旧库存投影、角色卡显示和回归测试。
- Non-goal: 批量重写玩家存档、改动过去战斗、实现所有消耗品/卷轴自动结算或重做武器熟练系统。

## Relevant context and files

- `backend/starter_shop.py`、`backend/rules_catalog.py`：现有装备目录只按英文精确匹配。
- `backend/game_logic.py`、`backend/agent_tools.py`：拾取链路未补全装备资料。
- `backend/main.py`、`frontend/src/App.jsx`：库存与攻击显示。
- 本地 `E:/5e Tools/data/items-base.json`、`items.json` 的 XPHB/XDMG 条目及本项目法术目录作为数据依据；运行时不依赖外部目录。

## Progress

- [x] 核对相关 active 计划与代码，确认中文目录匹配和拾取资料缺失。
- [x] 完成规则补全、效果元数据与前端显示。
- [x] 完整回归与合成浏览器验收。
- [x] 核对基线后同步工作区和长期文档。

## Decisions

- 2026-09-06：使用确定性目录补全，旧库存以只读投影显示，不在 GET 中修改游戏状态。
- 2026-09-06：保留自定义备注和明确效果；无法确定的效果不能猜骰数。卷轴必须明确法术，区分基础效果与升环说明。

## Discoveries / surprises

- 拾取工具未开放已有伤害字段；显示层另算攻击加值，与规则层存在重复逻辑。
- `use_item` 当前仅消耗库存，效果显示不能声称它已经自动结算所有治疗或卷轴效果。

## Validation

- 完整后端回归：396 项，395 通过、1 项真实 CLI opt-in 跳过。
- 前端 build 通过，lint 0 errors、2 条已有 Hook warning；15 项 Node 回归通过。
- 新增回归覆盖中文拾取、旧库存只读补全、数值一致、治疗/投掷物、卷轴限定语、错误无状态写入和不同环级不混叠。
- Chrome 合成旧库存验收：弯刀 1d6+2 挥砍、药水 2d4+2、强酸 2d6 及豁免条件可见；卷轴浮层保留每发伤害、次数与升环说明。
- 实际模型是否正确填写未知自定义物品资料未验证；本次浏览器使用临时合成存档，未操作玩家记录。
- 同步前校验文件哈希，12 个源文件与通过测试的副本一致；此前修改保留。
- 实际后端已重载，OpenAPI 包含 rules_name、healing_expression、spell_name 等新字段。
- Markdown 链接与 git diff --check 通过；仅已有换行符提示。
- 临时合成验收服务和页面已关闭。

## Remaining work

- 无。

## Resume instructions

1. 核对当前源文件及本计划。
2. 使用 `output/combat-control-fix` 隔离副本；本任务基线在 `output/item-metadata-baseline`。
3. 不读取真实存档、凭据或完整会话。

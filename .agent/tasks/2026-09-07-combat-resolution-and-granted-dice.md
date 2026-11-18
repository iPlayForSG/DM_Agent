# 战斗结算、临时武器与授予骰

Status: completed
Updated: 2026-09-07

## Goal

修复已完成工具被历史校验再次要求执行，以及错误规则反馈；补齐通用武器使用模式与诗人激励目标骰生命周期。

## Progress

- [x] 核对前次审计和本地2024手册的临时武器、攻击属性及诗人激励规则。
- [x] 分离当前校验与历史记录，约束规则反馈与回滚正文；无敌方存活时允许完成已声明的合法附赠动作再收尾。
- [x] 共用近战/投掷/临时武器解析，处理射程、熟练和物品离手。
- [x] 持久化授予骰，接入失败D20检定选择、消费、到期和状态投影。
- [x] 目标/完整测试、模型及合成浏览器验收；核对基线后同步18个文件，实际后端已加载新增API契约。

## Decisions

- 使用已有隔离工作副本；保留根目录既有修改，不读取玩家存档或重放真实行动。
- 激励骰独立于英雄激励；失败后决定消费，恢复不能重掷原D20。
- 随机恢复使用当前未完成工具的内部随机带，保存在checkpoint及服务端pending details；玩家响应过滤该内部字段。显示RollRecord仅作观察记录，并按固定record_id更新。

## Discoveries

- 最后校验已通过，实际没有重复攻击调用；历史修复文字导致模型误报规则冲突。
- 非投掷武器远程使用适用临时武器规则（1d4、20/60尺、通常无熟练）；正常远程属性为敏捷，投掷词条另有近战属性例外。
- 嵌套StructuredTool中随机子任务的task ID跨恢复不稳定，单独StateGraph测试不足以证明真实工具恢复正确；已增加实际DM子图暂停恢复回归。

## Validation

- Astra与Terra合成攻击击杀/激励场景均完成，2次骰点、1枚目标激励，战斗结束。移除多余advance_turn提示后Astra复验完成，工具顺序为attack_target、use_feature、end_encounter。
- 前端build通过，lint 0 errors/2既有warnings，28 Node tests通过。
- 隔离完整后端470 tests：469通过，1项可选CLI测试跳过；真实CLI验收另行执行。
- Chrome合成游戏验证：状态栏显示来源及1d6；失败后暂停，选择使用后仅两条骰点（原D20=8，激励=4，总值12），均已记录，激励状态消失。
- 根目录OpenAPI确认attack_mode与特性target_ref已由实际后端提供。未读取/重放玩家原存档；旧失败回合未自动修改。

## Remaining work

无本任务剩余工作。未提交或推送；当前回合未要求Git发布。

## Resume instructions

参照前置审计 `2026-09-07-post-combat-rollback-audit.md`。本次基线保存在 `output/combat-resolution-baseline`；工作副本 `output/combat-control-fix`，同步前核对基线哈希。

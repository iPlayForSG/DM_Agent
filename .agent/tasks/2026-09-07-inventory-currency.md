# 物品栏统一管理货币

Status: completed
Updated: 2026-09-08

## Goal / User-visible outcome

按用户要求，所有实际持有的钱币仅由物品栏管理；奖励和支出使用确定性工具，旧金币余额迁入库存且不重复入账，人物卡不再显示独立金币余额。

## Scope

角色schema兼容迁移、建卡余额、CP/SP/EP/GP/PP收支与找零、工具/API所有权、物品叙事、前端显示和合成回归。仅读写合成验收存档，不手工修改玩家私有存档。

## Progress

- [x] 核对现有gold_gp、库存入口与本地2024钱币表。
- [x] 实现唯一库存来源、旧数据幂等迁移和原子货币收支。
- [x] 联动建卡、工具/API、物品叙事及前端。
- [x] 目标/完整测试、模型与浏览器验收，同步19个已验证文件并确认实际货币API可用。

## Decisions

- 以整数铜币计算价值，保留五种钱币的库存数量；余额不足失败不改变库存。需要找零时执行等值换算，不兑换宝石、古币等收藏品。
- 移除运行时独立gold_gp字段；旧输入通过版本化角色迁移进入金币库存。建卡目录中的gold_gp仍是预算配置。
- 使用现有隔离工作副本，开始前保存本次文件基线和哈希。

## Discoveries

- 修复前，货币奖励经add_inventory_item进入普通库存，同时存在独立整数gold_gp字段，且没有支出工具；现已由库存钱币和adjust_currency统一结算。

## Validation

- 完整后端481 tests：480通过，1项可选CLI跳过；包含11项本次专项测试。
- 前端build、28 Node tests通过；lint无错误、2条既有warning。
- Astra和Terra均只调用一次currency.adjust，19金币6银币支付7银币后余额为18金币9银币。
- Chrome合成旧存档：角色顶部无独立金币，库存显示金币19/银币6；付款后更新为金币18/银币9，正文记录金币-1、银币+3的找零净变化。
- 根目录后端23334已重新加载并提供actions/currency，实际前端5173已移除character.gold_gp展示。
- git diff --check通过；同步前核对基线，未覆盖先前修改。未手工改写玩家游戏文件。

## Remaining work / Resume instructions

本任务已完成。实现与复现位于output/combat-control-fix，基线output/inventory-currency-baseline。长期决定见[ADR-0004](../../docs/adr/0004-inventory-currency.md)。没有执行Git提交或推送。

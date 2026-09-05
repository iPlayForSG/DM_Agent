# 队伍卡片法术与物品说明及分支交付

Status: completed
Updated: 2026-09-05

## Goal

先提交、推送并合并已验证的后端修复到 main；在用户指定的 refactor/frontend-design 分支实现队伍状态卡片中戏法、法术和有说明物品的悬停详情，验证后提交、推送并合入 main。

## Scope / Non-goals

- 仅从规则库和角色物品现有数据展示说明，不生成规则内容或修改游戏结算。
- 兼容鼠标悬停、键盘焦点和触屏查看，浮层不能被侧栏裁切。
- 保留此前未提交修复；不提交玩家数据、凭据、生成截图或构建产物。

## Relevant context and files

- `backend/main.py` 的 action options 投影、`backend/rules_catalog.py` 和规则库查询。
- `frontend/src/App.jsx` 的 CharacterStatusCard、`frontend/src/index.css`、`frontend/DESIGN.md`。
- 既有流式与骰点任务已完成，当前分支为 refactor/backend-bugfix。

## Progress

- [x] 检查工作树、分支和远端；获取 origin 最新状态。
- [x] 提交并推送旧修复，合并到 main；合并无冲突，合并后完整后端回归通过。
- [x] 切换 refactor/frontend-design 并同步 main。
- [x] 补齐说明投影及可访问浮层；缺少说明的条目保留纯文本。
- [x] 完成目标回归、前端构建/lint、合成浏览器验收。
- [x] 提交、推送新功能并合入 main；功能提交 70e4e69，合并提交 de25c19 已推送，无冲突。

## Decisions

- 2026-09-05：使用用户指定的已有分支名，普通推送与合并，不重写远端历史。
- 2026-09-05：说明只作为服务端展示投影，不写回权威法术或物品状态。
- 2026-09-05：法术说明随 action options 的 spells.options 提供；物品保留模型字段，合并目录描述与现有备注。浮层通过 Portal 避免侧栏裁切，支持 hover/focus/click 与 Escape。

## Discoveries

- 队伍卡片把 cantrips/prepared 名称直接 join 为文本，尚无悬停入口。
- action options 存在法术选项和物品列表，可复用其规则库查询与现有刷新生命周期。
- 窄屏原页面存在约 1px 横向溢出；浮层在视口内且未增加该溢出，本任务不扩展为整体布局重构。

## Validation

- [x] 合并旧修复后的完整后端：285 项，284 通过、1 项可选 CLI 测试跳过；Hook 测试 30 项通过。
- [x] 新增说明 API 契约后完整后端：288 项，287 通过、1 项可选 CLI 测试跳过；验证中英文法术名称、说明兼容、物品备注/目录补充、不修改状态与缺省说明。
- [x] 前端 build 和 10 项 Node 回归通过；lint 0 errors、2 条既有 Hook dependency warning。
- [x] Playwright + 真实 API + 临时合成存档：交友术、魅惑人类及升环说明、物品备注、悬停移入浮层、Tab 焦点、Escape、长说明滚动、无描述纯文本、390px 窄屏点击和视口边界检查通过。桌面与窄屏截图已目视核对。
- [x] `git diff --check` 及暂存区检查通过；合并后的 backend/frontend/tests 与已验证功能分支相同。实际服务 health=ok，前端已提供新组件；合成服务和验收浏览器已关闭。

## Remaining work

- 本任务无剩余实现；真实触屏硬件、玩家存档长流程未在本次实测。

## Resume instructions

1. 继续前端工作时先核对 refactor/frontend-design 与 main 的远端状态；本次功能已交付。
2. 说明入口在 action options 展示投影与 DescriptionTooltip，不向角色法术列表写入目录说明。
3. 后续验证使用项目 Conda Python 和合成数据，不读取真实玩家存档或环境凭据。

# 2026-11-19 · 前端架构与视觉重构：曜金羊皮编年史（Illuminated Tabletop Chronicle）

Status: completed
Updated: 2026-11-19

## Goal

从 `main` 出发，在不改变任何后端 API 契约、SSE 流式传输、异步生命周期守卫及确定性规则逻辑的前提下，对前端进行完整的工程架构拆分与高品味视觉/交互重构：

1. 将超过 4,000 行的单体 `frontend/src/App.jsx` 拆分为职责清晰的本地化/格式化模块、自定义桌面图标组件、Markdown 叙事渲染组件、跑团会话与战局面板组件、角色卡详情组件与装备轮播组件，并消除遗留的 React Hooks ESLint 警告。
2. 彻底重写并去重 3,478 行的 `frontend/src/index.css`（清除早先暗色主题残留与后置覆盖层拼贴），落地「曜金羊皮编年史 · 现代桌面跑团台」视觉体系。
3. 重构大厅、建卡向导、角色册、跑团会话（叙事流 + 多标签右侧编年史/战局面板 + 紧凑顶栏 + 集成篇幅控制的行动输入坞）的布局与交互体验。

## User-visible outcome

- **大厅主页**：具备羊皮卷与黄铜纹章质感的英雄区与三张核心入口卡；模型设置默认呈现为高辨识度的引擎状态栏，支持一键展开完整配置工作台；存档与角色列表采用富有层次的桌面卡片与双步安全删除弹窗。
- **角色构筑向导（1–20 级）**：顶部常驻实时构筑摘要条（姓名、种族、背景、职业、等级、生命上限、属性/金币预算），经典的六维属性徽章卡片，清晰的装备套装/自定义商店分页轮播与法术卡片网格。
- **玩家角色册**：修复原先 6 列空缺的生命状态条，采用典藏角色卡版式展示六维属性、熟练、特性、资源、攻击、法术与物品栏。
- **跑团会话主桌**：移除占空间的 248px 空旷左侧栏，改为紧凑的顶部会话指挥栏（展示局名、场景阶段、回合数、模型状态、主桌/编年史视图切换与返回大厅）；叙事流呈现具有书籍章节质感的主持人卡片（含顶部骰盘折叠账本、思考流折叠面板、行内明骰/战斗/物品高亮）与玩家宣言气泡；底部行动输入坞内嵌叙事篇幅配置浮层与重写状态条；右侧面板支持「队伍与战局」和「线索与编年」就地切换，同时保留独立全屏「编年史」视图。

## Scope / Non-goals

- In scope:
  - `frontend/DESIGN.md` 设计规范升级
  - `frontend/index.html` 标题与图标升级
  - `frontend/src/App.jsx` 模块化拆分与 Hook 依赖修复
  - `frontend/src/dndLabels.js` 及 `frontend/src/components/*` 组件提取
  - `frontend/src/index.css` 全量重写与响应式精修
  - 前端单元测试、ESLint 零警告与 Vite 生产构建验证
- Non-goal:
  - 不修改 `backend/` 任何路由、模型或规则逻辑
  - 不改动 `frontend/src/api.js`、`retryUi.js`、`rollUi.js`、`narrativeRollUi.js`、`descriptionTooltipState.js`、`descriptionMarkdown.js` 的核心契约

## Relevant context and files

- `frontend/DESIGN.md`：前端视觉与交互唯一设计锚点
- `frontend/src/App.jsx`：主状态容器与视图编排
- `frontend/src/dndLabels.js`：D&D 2024 中文化字典与纯格式化工具函数
- `frontend/src/components/Icons.jsx`：定制 SVG 跑团桌面图标集
- `frontend/src/components/MarkdownBlock.jsx`：对话引语高亮与行内骰点/战斗/物品标记渲染
- `frontend/src/components/ShopCarousel.jsx`：构筑选项按钮与商店分类分页轮播
- `frontend/src/components/CharacterSheetDetail.jsx`：完整角色卡展示组件与法术浮层触发列表
- `frontend/src/components/SessionPanels.jsx`：骰点账本、DM 思考面板、队伍角色状态卡、行动额度、场上先攻面板、时间线、线索与战役见闻面板
- `frontend/src/index.css`：全新的设计 token 与组件样式表

## Progress

- [x] 读取 `AGENTS.md`、`.agent/memory/`、`frontend-design` 技能与现有前端全部源码
- [x] 盘点现有前端视觉痛点、代码坏味道与所有业务状态守卫契约
- [x] 更新 `frontend/DESIGN.md` 设计锚点与 `frontend/index.html`
- [x] 拆分创建 `frontend/src/dndLabels.js`、`frontend/src/dndLabels.test.mjs` 与 `frontend/src/components/*`
- [x] 重构 `frontend/src/App.jsx` 并修复全部 ESLint 警告
- [x] 重写 `frontend/src/index.css`
- [x] 运行前端单测、`npm run lint`、`npm run build` 与 `git diff --check`

## Decisions

- 2026-11-19：保持亮色暖羊皮纸与赤陶红/鼠尾草绿/古黄铜的核心色彩基因（符合 `DESIGN.md` 不回归暗色后台的约束），将风格深化为「曜金羊皮编年史（Illuminated Tabletop Chronicle）」，彻底清理 `index.css` 中残留的暗色样式与后置覆盖层。
- 2026-11-19：会话页采用顶部指挥栏 + 主叙事流 + 右侧多标签辅助栏（支持就地切换「队伍与战局 / 线索与编年」，并保留顶部「对话 / 时间线」全屏视图切换），既释放约 250px 水平叙事空间，又让玩家无需离开聊天即可查阅线索与世界见闻。
- 2026-11-19：大厅模型设置改为「紧凑状态横幅 + 按需展开的配置工作台」（当模型未就绪时自动展开提醒，用户也可随时一键展开编辑/新建档案），避免 7 个表单输入框常驻割裂大厅的跑团桌面氛围。

## Discoveries / surprises

- `frontend/src/index.css` 长达 3,478 行，其中 2,777 行之后是后来追加的 `Visual refinement layer`，大量选择器重复定义甚至互相覆盖；且 token 命名中 `--ink` 实际是背景色、`--paper` 实际是文字色。本次重写后精简去重为清晰的语义 token 与模块化样式。
- `CharacterSheetDetail` 的 `.sheet-vital-strip` 原先定义了 6 列网格但仅渲染 5 项数据；`CharacterStatusCard` 的 `.party-vitals` 原先定义了 4 列网格但仅渲染 3 项数据，导致右侧常驻空白槽位，已全部修正。
- `App.jsx` 原先存在 2 处 `react-hooks/exhaustive-deps` lint 警告（初始化 `refreshLobby` 与 `actionOptions` 同步 `actionDraft.attack`），已通过 `useCallback` 与纯函数 `buildAttackDraftFromActors` 彻底消除。

## Validation

- [x] `node --test src/*.test.mjs` — 31 项测试全部通过
- [x] `npm run lint` — 0 errors, 0 warnings
- [x] `npm run build` — Vite 生产构建通过
- [x] `git diff --check` — 空白与格式检查通过
- [ ] 真实浏览器交互实测 — 未验证（已在单元/构建层验证，建议在浏览器中预览新视觉效果）

## Remaining work

- 无阻塞项；用户可在浏览器中实际体验「曜金羊皮编年史」新界面。

## Resume instructions

1. 阅读本文件与 `frontend/DESIGN.md`。
2. 检查 `frontend/src/` 下各模块拆分进度并运行 `npm run lint` 与 `npm run build`。

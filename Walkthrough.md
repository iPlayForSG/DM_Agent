# DM_Agent Walkthrough

## 1. 这份文档的用途

这是一份给“下一次对话中的开发者/代理”使用的交接文档。

目标：

1. 说明项目最终想实现什么。
2. 说明当前代码已经做到哪里。
3. 说明下一步最应该做什么。
4. 说明现在仓库里哪些文件负责什么。
5. 说明如何在本地继续运行、验证和扩展。

## 2. 项目最终目标

这是一个以 D&D 5e 2024 为规则基准的单人跑团 Agent。

理想形态应覆盖以下完整流程：

1. DM 引导用户创建角色。
2. 用户按规则创建 1 到 4 人初始小队。
3. DM 生成若干初始剧本摘要，用户选择其一。
4. 正式进入冒险流程，用户与 DM 对话推进剧情。
5. 在整个过程中，本地持续维护并保存小队角色数据：
   - 生命值、临时生命值
   - 经验值或里程碑状态
   - 法术位
   - 已知/已准备法术
   - 装备、消耗品、金钱
   - 灵感
   - 状态效果
   - 职业资源
   - 重大经历摘要
6. 进入战斗时，自动切到战斗态：
   - 显示参战者简要状态
   - 显示回合/先攻
   - 显示敌我单位
   - 控制法术位、资源、消耗品的合法使用
7. 所有骰子通过本地脚本/本地逻辑生成。
8. 升级时给出升级模板或升级流程，并按 2024 规则更新角色。
9. 长期上支持：
   - 怪物模板
   - 模块/剧本摘要
   - 规则知识库与怪物百科参考
   - 更完整的 Rules Guard

## 3. 当前已经实现的内容

当前版本已经不是空壳，已经有一个可运行的最小闭环。

### 3.1 模型与运行链路

已经实现：

1. 后端使用 FastAPI。
2. 后端用 Google ADK + LiteLlm 跑 OpenAI 兼容模型。
3. 当前 `.env` 已切到本机 Codex 代理，并使用 `gpt-5.1`。
4. 游戏真相保存在本地 `GameState` JSON 中，而不是只存在模型上下文里。
5. Agent 已接入本地规则检索工具 `lookup_rules`，优先走 Chroma 向量库，缺少 `chromadb` 时可退回到本地 markdown 词法检索。
6. Python 环境使用 conda 的 DM_Agent 虚拟环境

### 3.2 角色与规则目录

已经实现：

1. 角色模板的本地保存与读取。
2. 角色模型中已经加入：
   - `species`
   - `background_name`
   - `origin_feat`
   - `skill_proficiencies`
   - `save_proficiencies`
   - `resources`
   - `spells`
   - `inventory`
   - `major_experiences`
3. 本地规则目录 `character_builder_2024.json`。
4. `RuleCatalog` 已能提供：
   - 种族/物种
   - 背景
   - 起源专长
   - 职业目录
   - 职业技能可选项
   - 起始法术位
   - 起始职业资源
   - 起始装备
5. 保存角色时会自动：
   - 校验背景/职业/法术是否合法
   - 自动填充起始资源
   - 自动填充起始法术位
   - 自动填充起始装备
   - 自动推导基础 AC

### 3.3 跑团流程状态

已经实现：

1. `CampaignFlowState`
2. 游戏创建后自动进入 `adventure_selection`
3. 后端自动生成 3 个初始剧本摘要
4. 用户选择剧本后切换到 `exploration`

### 3.4 怪物模板

已经实现：

1. `MonsterTemplate` 数据模型
2. `MonsterStorage`
3. 怪物模板 API
4. ADK 工具可保存怪物模板
5. ADK 工具可从模板生成怪物并加入遭遇

### 3.5 战斗与动作

已经实现：

1. 最小 `EncounterState`
2. 先攻顺序
3. 当前行动者
4. 推进回合
5. 角色或战斗单位 HP 修改
6. 状态添加/移除
7. 攻击结算
8. 技能检定
9. 豁免检定
10. 施法合法性校验
11. 法术位消耗
12. 物品使用与数量扣减
13. 结束遭遇时统一生成结果摘要并写入 `adventure_log`，公开 HTTP 接口与 ADK 工具共用同一逻辑
14. 遭遇建立后会在先攻齐备时锁定真正的当前行动者，本地动作会拒绝越过当前回合的人抢行动
15. 攻击现在支持非致命/俘获结算，并把 `dead / unconscious / captured` 结果写入结构化状态
16. ADK 现在可以把证物/战利品写入 `inventory`，把重大经历写入 `major_experiences`，并记录章节标题与章节总结

### 3.6 结构化时间线

已经实现：

1. `SessionEvent`
2. 每轮会返回：
   - `history`
   - `history_append`
   - `timeline`
   - `timeline_append`
   - `tool_results`
   - `state_delta`
   - `game_state`

### 3.7 前端

已经实现：

1. 首页
2. 角色创建页
3. 怪物模板页
4. 新游戏创建页
5. 初始剧本选择页
6. 聊天页
7. 状态页
8. 最小战斗操作层

前端当前已经能：

1. 调用规则目录接口。
2. 创建角色。
3. 创建怪物模板。
4. 进入游戏。
5. 选择初始剧本。
6. 发送自由文本到 DM。
7. 从聊天侧栏执行：
   - 推进回合
   - 攻击
   - 施法
   - 技能检定
   - 豁免检定
   - 使用物品
8. 在攻击表单里从 `action-options.attacks` 自动同步攻击元数据，并显式选择普通/非致命/俘获结算模式。

## 4. 当前没有完成的内容

虽然已经有不少基础，但离目标形态还有明显差距。

### 4.1 角色创建器仍不完整

还缺：

1. 更完整的 2024 角色构建规则。
2. 更清晰的起始装备展示。
3. 更清晰的起始资源展示。
4. 更清晰的起始法术位展示。
5. 更细的法术选择限制与 UI 提示。

### 4.2 战斗操作层仍偏原型

还缺：

1. 更完整的怪物动作自动映射。
2. 更好的施法选项展示。
3. 更好的资源耗尽反馈。
4. 更清晰的“当前行动者”操作约束。

### 4.3 Rules Guard 仍不完整

还缺：

1. 更完整的 2024 职业特性校验。
2. 更完整的专长校验。
3. 更完整的法术准备/已知规则。
4. 更完整的装备熟练、护甲影响与武器规则。
5. 升级规则。

### 4.4 长期跑团系统还没做完

还缺：

1. 升级模板与升级流程。
2. 更完整的经验/里程碑模式。
3. 长休/短休规则流。
4. 剧本管理与更多模块内容。
5. 更高质量的 RAG 切片、召回与排序。

## 5. 关键文件说明

### 5.1 后端核心

`backend/main.py`
负责 FastAPI 路由，暴露角色、怪物、游戏、规则目录、剧本选择和动作接口。

`backend/agent.py`
负责 Google ADK 主链路，处理 DM 文本轮次和 ADK 工具调用。

`backend/action_service.py`
负责不经过大模型的本地动作接口：
- 攻击
- 施法
- 技能检定
- 豁免检定
- 使用物品
- 推进回合
- 结束遭遇与结果摘要落库
- 结构化写入物品、重大经历与章节进度

`backend/game_logic.py`
负责本地游戏真相修改：
- 遭遇
- 先攻
- 回合推进
- HP
- 状态
- 怪物实例化
- 遭遇总结与结束摘要生成
- 非致命/俘获结果与章节记录

`backend/models.py`
定义主要数据模型：
- Character
- MonsterTemplate
- GameState
- CampaignFlowState
- EncounterState
- SessionEvent

### 5.2 后端规则与数据

`backend/rules_catalog.py`
本地规则目录服务与 Rules Guard 第一版。

`backend/adventure_service.py`
初始剧本摘要生成逻辑。

`backend/library.py`
法术资料库读取。

`backend/rag.py`
Agent 规则检索层；优先使用 Chroma，缺依赖时退回到基于 `rg` 的本地 markdown 检索。

`backend/rag_ingest.py`
离线构建或重建本地知识库索引。

`backend/data/character_builder_2024.json`
角色创建规则目录数据。

`backend/data/spells.json`
法术资料库。

### 5.3 后端存储

`backend/storage.py`
本地 JSON 持久化。

目录约定：

- `backend/Characters`
- `backend/Monsters`
- `backend/Game`

### 5.4 前端

`frontend/src/App.jsx`
当前所有前端页面和状态流都集中在这里。

`frontend/src/api.js`
前端 API 封装层。

`frontend/src/index.css`
页面样式。

`frontend/vite.config.js`
Vite 代理配置。

### 5.5 文档

`BACKEND_API_DESIGN.md`
后端顶层 API 设计说明。

`FRONTEND_API_DESIGN.md`
前端顶层 API 设计说明。

`Walkthrough.md`
当前这份交接文档。

## 6. 当前主要接口一览

### 6.1 基础

- `GET /api/v1/health`
- `GET /api/v1/config`

### 6.2 规则与资料

- `GET /api/v1/rules/character-builder`
- `GET /api/v1/library/classes`
- `GET /api/v1/library/spells/{class_name}`

### 6.3 角色与怪物模板

- `GET /api/v1/characters`
- `POST /api/v1/characters`
- `GET /api/v1/characters/{identifier}`
- `GET /api/v1/monsters`
- `POST /api/v1/monsters`
- `GET /api/v1/monsters/{identifier}`

### 6.4 游戏流程

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

其中 `POST /api/v1/games/{game_id}/encounters/end` 现在会生成统一的遭遇结果摘要、写入 `adventure_log`，并与 ADK 的 `end_encounter` 工具保持一致。

### 6.5 本地动作

- `POST /api/v1/games/{game_id}/actions/advance-turn`
- `POST /api/v1/games/{game_id}/actions/attack`
- `POST /api/v1/games/{game_id}/actions/skill-check`
- `POST /api/v1/games/{game_id}/actions/saving-throw`
- `POST /api/v1/games/{game_id}/actions/cast-spell`
- `POST /api/v1/games/{game_id}/actions/use-item`

其中 `attack` 现在支持非致命结算，会把目标的击倒结果写成结构化 `defeat_state`。

## 7. 已验证内容

已经跑过并通过的验证：

1. `conda activate DM_Agent`
2. `python -m compileall backend`
3. `npm run build`
4. 角色创建接口 smoke test
5. 游戏创建与初始剧本选择 smoke test
6. 施法合法性 smoke test
7. 本地动作接口 smoke test
8. 起始装备/资源与自动推导攻击项 smoke test
9. 结束遭遇摘要与 `adventure_log` 一致性 smoke test（公开接口路径与 ADK 共享结果）
10. 先攻排序与当前行动者一致性 smoke test
11. 非致命击倒与遭遇总结分类 smoke test
12. 证物/重大经历/章节记录落库 smoke test

## 8. 已知问题与注意点

### 8.1 前端主文件目前较大

`frontend/src/App.jsx` 目前是单文件大组件，后续继续开发时最好逐步拆分。

### 8.2 中文显示与本地控制台编码

PowerShell/conda 在某些输出场景会有编码噪音，但不影响核心逻辑。

### 8.3 法术资料库的职业名存在编码历史问题

后端已经通过 `RuleCatalog.resolve_spell_library_key()` 做了映射兼容，不要直接假定法术库里的职业 key 与前端职业显示名一致。

### 8.4 action-options 仍可继续丰富

目前虽然已经能返回攻击项、法术、物品、资源，但前端还没有把这些信息完全自动填满动作表单。

### 8.5 后续后端改动保持简短注释

当前后端 Python 文件已经补了一层简短注释。后续继续开发时，默认保持同样风格：

- 每个模块有一句职责说明
- 复杂状态同步、战斗流程、持久化写入前后补一句简短注释
- 注释解释“为什么这里这样做”，不要写成重复代码字面的废话

## 9. 下一步最应该做什么

如果下一次对话继续开发，优先级建议如下：

1. 继续细化战斗操作层：
   - 更完整的怪物动作自动映射
   - 更好的资源耗尽反馈
   - 更清晰的当前行动者约束与动作禁用态
2. 在角色创建页明确展示：
   - 起始装备
   - 起始职业资源
   - 起始法术位
3. 继续完善角色 builder：
   - 更完整的装备选择
   - 更完整的技能/专长限制
   - 更完整的法术选择限制
4. 优化 RAG：
   - 补齐 `chromadb` 运行依赖
   - 改善检索 query 重写、召回排序和片段截断
   - 逐步接入怪物百科与模块文本
5. 做升级模板与升级流程。

## 10. 下次进入仓库后建议的第一步

建议下次先做：

1. 打开 `Walkthrough.md`
2. 读一遍：
   - `backend/main.py`
   - `backend/rules_catalog.py`
   - `backend/action_service.py`
   - `frontend/src/api.js`
   - `frontend/src/App.jsx`
3. 跑一次：
   - `conda activate DM_Agent`
   - `python -m compileall backend`
   - `cd frontend && npm run build`
4. 然后从“战斗控制面板细化”继续开发

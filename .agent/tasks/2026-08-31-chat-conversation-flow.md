# 会话选择定位与玩家消息即时反馈

Status: completed
Updated: 2026-09-05

## Goal

修复会话页两个连续性问题：暂停时先补回触发交互的玩家原始发言，再把待玩家选择/确认的交互卡放在其下方；玩家发送发言或选择后立即在消息流中显示玩家气泡，再与服务端权威快照对账。

## Design read

- 页面类型：实时跑团会话页。
- 用户：正在阅读 DM 叙事并立即作出回应的玩家。
- 功能契约：玩家发言发送后立即可见；待处理选择紧跟对应 DM 叙事；服务端成功后不重复、不闪烁；失败时明确反馈并可重试。
- 拨盘：视觉冒险度 4 / 动效强度 3 / 信息密度 6。
- 模式：沿用方向 D“冒险面板”，本次仅打磨对话流，不改变整体视觉语言。

## Component dossier

- Pattern：按时间排序的消息流；暂停快照回滚聊天历史时，从 `pending_turn.original_input` 恢复只读的玩家上下文消息，再插入当前待处理交互。
- Anatomy：DM/玩家消息、待处理选择或确认、发送状态、工作流状态、主持输入区。
- States：普通消息、玩家消息发送中、玩家消息发送失败、等待 DM、待选择、待确认。
- Keyboard：输入框 Enter 发送；选择按钮使用原生 button，Tab 可达，Enter/Space 触发。
- Narrow viewport：交互卡保持在消息流内并自然换行，不创建横向滚动。
- Overflow：长提示与按钮标签允许换行；消息流负责纵向滚动。
- Recovery：发送失败的气泡保留失败状态，同时把原文恢复到输入框；再次发送时替换旧失败气泡。

## DNA injection

采用 Notion 设计系统中的三个具体值，并服从项目既有色板：

1. `1px` 轻描边保持待处理交互和消息卡层级清楚。
2. `12px` 圆角延续会话卡片与玩家气泡的统一几何。
3. `8px` 基础节奏组织气泡、状态提示和选择按钮间距。

## Progress

- [x] 在真实浏览器和用户当前存档中复现选择卡置顶问题。
- [x] 将会话交互契约补充到 `frontend/DESIGN.md`。
- [x] 移动待处理交互到消息流末端。
- [x] 用暂停状态的原始输入恢复玩家上下文消息。
- [x] 实现玩家消息乐观插入、权威快照对账和失败恢复。
- [x] 完成浏览器两轮检查与前端门禁。
- [x] 提交并推送 `refactor/frontend-design`。

## Decisions

- `GameState.chat_history` 仍是权威历史；浏览器只暂存单条发送中的玩家消息，不复制规则或持久化事实。
- 当前后端一次只允许一个回合请求，因此会话最多保留一个乐观玩家气泡；重试时替换先前失败气泡。
- 暂停事务公开的是回滚后的 `chat_history`，但 `pending_turn.original_input` 是该暂停的公开上下文；只读展示它，不给删除或重写操作。

## Validation

- 应用内浏览器复现：修复前待选卡位于全部历史消息之前。
- 应用内浏览器布局复测：待选卡已移到最后一条可见对话之后、主持输入区之前。
- 应用内浏览器真实交互：点击“暂不决定”后服务端快速完成对账，最终只保留一条原始玩家发言和一条取消回复，无重复气泡。
- 代码路径检查：暂停快照使用公开的 `pending_turn.original_input` 恢复只读玩家上下文，刷新后仍可重建位置。
- `npm run build`：通过（Vite 288 个模块）。
- `npm run lint`：0 error；保留仓库原有 2 条 `react-hooks/exhaustive-deps` warning。
- `C:\Users\iPlayForSG\.conda\envs\DM_Agent\python.exe -m unittest tests.test_builder_localization -v`：3 项通过。
- `git diff --check`：通过，仅有 Git 的 LF/CRLF 提示。

## Craft loop review

- 艺术总监：第一轮只把选择卡移到最后一条 DM 叙事后，视觉层级已连贯，但仍缺玩家发言这一层上下文。
- 工程师：第二轮改用 `pending_turn.original_input` 派生只读消息，不把未提交事务伪装成可删除的权威聊天记录。
- 甲方：玩家现在能沿“我刚说了什么 → DM 需要我选什么”的顺序阅读，不再需要回到页面顶部寻找交互。
- 读者：发送中与失败状态放在玩家气泡下方；失败原文回填输入框，恢复路径明确。

## Remaining work

无。

## Resume instructions

任务已完成；后续调整暂停交互时继续保持 `chat_history` 的权威边界，并把 `pending_turn.original_input` 仅作为只读显示上下文。

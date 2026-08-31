# 主持人实时思考流与次级幻象骰点审计

Status: completed
Updated: 2026-08-31

## Goal

让游戏会话页在主持回合执行期间实时接收并展示公开的 Agent 输出与工作流进度；内容按 Markdown 引用语义展示，回合结束后自动折叠且允许重新展开。同时只读核对游戏 `111` 中“次级幻象”回合是否发生骰点。

## User-visible outcome

- 玩家发送消息后，不再只看到静态“主持人思考中…”，而会看到持续到达的公开 Agent 输出和阶段进度。
- 思考区运行时展开，完成后自动收起；小尖角按钮可再次展开，键盘和屏幕阅读器可操作。
- 游戏 `111` 的骰点结论有工具记录与时间线证据支持，不修改存档或规则。

## Scope / Non-goals

- In scope：`backend/main.py` 的 SSE 并发出流、LangGraph 模型输出事件、`frontend/src/api.js` 事件分发、`frontend/src/App.jsx` 思考区状态、`frontend/src/index.css` 样式及相关测试。
- Non-goal：不公开模型隐藏 chain-of-thought；不让流式草稿或进度改变 `GameState`；不修复或重写游戏 `111`；不改变最终回合提交和回滚语义。

## Relevant context and files

- `backend/main.py`：当前 SSE 会等待完整回合结束后才发送 trace，需改为 worker task + async queue。
- `backend/dm_graph.py`：模型目前使用 `invoke`；流式请求中可使用 LangChain `stream` 并累积同一权威消息。
- `backend/model_backends.py`：Codex/Claude CLI transport 没有逐 token `_stream`，因此需要由实时节点事件提供 provider 无关的持续反馈。
- `frontend/src/api.js`：SSE parser 已支持自定义事件，只需增加 Agent 输出分发。
- `frontend/src/App.jsx`、`frontend/src/index.css`：替换静态 loading 文案为渐进披露的 Markdown 引用区。
- `tests/test_main_streaming.py`：验证事件顺序、真正早于回合完成的 live 事件与错误路径。
- `backend/Game/111.json`：只读审计来源，不提交、不修改、不输出完整 transcript。

## Progress

- [x] 核对分支并确认会话开始时工作树干净。
- [x] 审计现有 SSE、LangGraph 模型调用、前端 loading/trace UI。
- [x] 审计游戏 `111` 的“次级幻象”回合与骰点记录。
- [x] 实现线程安全的实时回合事件桥和模型输出增量。
- [x] 实现前端 Markdown 引用思考区与自动折叠。
- [x] 补充测试并完成后端、前端、差异与浏览器验证。

## Decisions

- 2026-08-31：思考区只展示可公开的模型文本与简洁阶段进度，不宣称或暴露隐藏 chain-of-thought。
- 2026-08-31：流式文本只是观察通道；`finalize_turn`、存档保存和最终 `TurnResult` 仍是唯一权威提交路径。
- 2026-08-31：SSE 运行时使用 async queue 消费后台线程事件，避免阻塞到整个 LangGraph 回合结束。
- 2026-08-31：OpenAI-compatible 模型在流式上下文中使用 LangChain `stream` 取得 token；不支持 token stream 的 CLI provider 仍实时发送节点进度，并在每个模型步骤完成时发送完整文本块。
- 2026-08-31：思考区采用渐进披露组件，不使用 modal/popover；运行时展开、完成时自动折叠，错误后保留可重新展开的内容。

## Discoveries / surprises

- 现有 `/turns/stream` 名为流式接口，但 `await _execute_turn_and_save(...)` 完成后才依次发送节点和细节事件，因此玩家端没有实时增量。
- 本机 `codex exec --help` 提供 `--json` JSONL 事件输出，但当前项目的结构化 CLI transport 只实现 `_generate`；本次用 provider 无关的节点进度保证实时性，并在支持 LangChain token stream 的 provider 上提供真实 token 增量。
- 游戏 `111` 第 5 回合只记录成功的 `magic.cast_spell`；该工具 payload 无 d20/DC/调查结果，且游戏时间线没有 `dice_result`，所以该次没有掷骰。
- 长对话中的思考面板起初被纵向 flex 的默认收缩压成 2px，浏览器命中测试只能落到外层容器；为面板设置 `flex: 0 0 auto` 后恢复完整高度与点击能力。
- 手动重新展开长思考内容时，不应因为 `expanded` 状态变化自动滚到内容末尾；实时运行仍由消息、节点和输出增量驱动自动滚动。

## Validation

- [x] `python -m unittest tests.test_main_streaming -v` — 20 项通过，覆盖 live 事件在回合完成前到达及输出事件顺序。
- [x] `python -m unittest discover -s tests -v` — 沙箱内首次因 Windows 系统临时目录权限出现 12 个环境错误；沙箱外同命令 214 项全部通过。
- [x] `npm run build` — 通过；沙箱内首次因 `spawn EPERM` 失败，批准后重跑成功。
- [x] `npm run lint` — 通过，0 error；保留 2 个会话前已存在的 hooks 依赖 warning。
- [x] 浏览器真实流式回合 — 在游戏 `111` 的临时副本上确认回合未结束时节点与公开模型文本已到达、运行态展开、完成态自动折叠、鼠标小尖角重新展开、`blockquote` 与 `aria-expanded` 语义正确；临时存档及 rewind 已删除。未单独模拟窄屏视口。
- [x] `git diff --check` — 通过，仅有仓库既有的 LF/CRLF 工作树提示。
- [x] `git status --short --branch` — 最终分支为 `refactor/backend-bugfix`，只有本任务涉及的代码、测试、设计锚和 ExecPlan 发生变化。

## Remaining work

- 无。

## Resume instructions

任务已完成。后续若扩展其他 CLI provider 的逐 token 输出，先确认其 transport 能提供结构化增量；不要让观察性流改变 `finalize_turn` 的权威提交边界。

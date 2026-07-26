# 模块地图

## 后端入口与编排

| 模块 | 目的/对外接口 | 主要依赖 | 修改时联动检查 |
| --- | --- | --- | --- |
| `backend/main.py` | `/api/v1/*`、SSE、错误映射、存档事务 | agent facade、storage、action service | `models.py`、`frontend/src/api.js`、API 契约测试 |
| `backend/agent.py` | 模型档案、Agent 生命周期、turn/resume facade | `dm_graph.py`、dotenv | health/config API、密钥脱敏、provider smoke |
| `backend/dm_graph.py` | LangGraph 父图、路由、审计、提交 | agents、tools、RAG、models | phase policy、工具预算、trace、workflow tests |
| `backend/agents/` | 角色定义、私有子图、工具适配 | LangChain/LangGraph、tool registry | `specs.py` ownership、runtime topology tests |

逐端点清单不在 memory 中重复维护：后端定义以 `backend/main.py` 的 FastAPI 路由和 `backend/models.py` 的 schema 为准；浏览器消费契约以 `frontend/src/api.js` 和相关 API 测试为准。

## 规则与状态

| 模块 | 目的/对外接口 | 主要依赖 | 修改时联动检查 |
| --- | --- | --- | --- |
| `backend/models.py` | `Character`、`EncounterState`、`GameState`、请求/响应 schema | Pydantic | JSON 兼容、API、前端字段、rewind、测试 fixture |
| `backend/tool_registry.py` | 工具 schema、风险和运行前守卫 | models、rules catalog | agent specs、phase allowlist、tool tests |
| `backend/agent_tools.py` | Agent 工具执行与统一 `ToolResult` | GameLogic、RuleCatalog | action service 对称行为、timeline、delta |
| `backend/action_service.py` | 本地动作 API 的确定性执行 | GameLogic、RuleCatalog | agent tool 行为、main routes、action options |
| `backend/game_logic.py` | 骰子、攻击、伤害、先攻、镜像同步 | models | current actor、action ledger、concentration、combat tests |
| `backend/rules_catalog.py` | 构筑目录、派生值、法术/装备校验 | JSON catalog、ability service | builder API、角色保存、攻击/法术工具 |
| `backend/ability_scores.py` | 购点、标准数组、4d6 去最低和记录验证 | RuleCatalog constants | builder UI、Character schema、相关测试 |

## 内容、存储与检索

| 模块 | 目的/对外接口 | 修改时联动检查 |
| --- | --- | --- |
| `backend/storage.py` | JSON CRUD、完整 rewind snapshot | schema 版本、路径安全、delete/rewrite API |
| `backend/adventure_service.py` | 固定/AI 冒险生成与 D&D 风格校验 | setup flow、campaign schema、测试 |
| `backend/rag.py` | 多查询、重排、来源去重、上下文截断 | health/status、dm_graph rules stage |
| `backend/rag_embeddings.py` | GGUF 定位、llama-server 生命周期、embedding | Windows 路径、GPU/CPU 环境、超时与日志 |

## 前端

| 模块 | 目的/对外接口 | 修改时联动检查 |
| --- | --- | --- |
| `frontend/src/api.js` | API base URL、REST、SSE parser、错误标准化 | `main.py` 路由和响应 schema |
| `frontend/src/App.jsx` | 大厅、构筑、游戏、战斗、分支和异步生命周期 | `api.js`、action options、CSS、build/lint |
| `frontend/src/index.css` | 当前主要视觉与响应式样式 | App class names、浏览器检查 |

这不是完整文件列表。新增公共模块、移动职责或改变边界时更新本表；局部 helper 不需要记录。

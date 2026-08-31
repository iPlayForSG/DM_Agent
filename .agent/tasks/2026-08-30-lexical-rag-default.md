# 词法规则检索默认化

Status: completed
Updated: 2026-08-30

## Goal

让 DM_Agent 默认通过本地 heading-aware grep/词法索引检索规则，不加载或调用 GGUF embedding；向量检索保留为显式可选模式。

## User-visible outcome

默认启动和规则查询不再依赖 Chroma、llama.cpp 或 embedding 模型。用户需要向量语义检索时可显式设置 `RAG_RETRIEVAL_MODE=vector`，且向量失败仍会回退词法索引。

## Scope / Non-goals

- In scope：RAG 路由默认值、状态字段、环境示例、测试、ADR/README/memory。
- Non-goal：删除向量索引构建能力、改变词法评分算法、调用外部模型验证规则正文。

## Relevant context and files

- `backend/rag.py`：运行时检索路由与状态。
- `tests/test_rag_fallback.py`：词法/向量行为测试。
- `backend/.env.example`、`README.md`：默认配置与使用说明。
- `docs/adr/0002-model-transports-and-lexical-rag-fallback.md`：模型传输与检索决策。

## Progress

- [x] 核对当前实现，确认现状为向量优先、词法失败降级。
- [x] 实现 lexical 默认与 vector 显式启用。
- [x] 完成目标、全量和文档验证。

## Decisions

- 2026-08-30：使用 `RAG_RETRIEVAL_MODE=lexical|vector`，默认 `lexical`；不用含糊的自动探测决定是否调用 embedding。
- 2026-08-30：`vector` 模式保留词法兜底，但默认 lexical 模式不把“未加载向量”报告成错误或 fallback。

## Discoveries / surprises

- 当前 `RAGEngine` 构造时会先打开 Chroma；查询时只要 collection 存在就调用 `get_query_embedder()`，因此仅准备好向量库也会让默认路径启动 embedding 模型。
- 验证结束时工作区被外部从 `main` 切到同一基线的 `refactor/frontend-design`，并出现无关的 `design-previews/`；本任务没有切换分支、读取或修改这些预览文件。

## Validation

- [x] `python -m unittest tests.test_rag_fallback -v` — 10 项成功。
- [x] `python -m unittest discover -s tests -v` — 200 项成功。
- [x] 本机规范化语料 smoke — `mode=lexical`、`backend=lexical-grep`、`vector_ready=false`、无 vector error/fallback，返回 1 项结果。
- [x] `npm run build` — 成功。
- [x] `npm run lint` — 0 errors，2 条既有 Hook dependency warning。
- [x] `git diff --check` — 通过，仅有工作区 LF/CRLF 提示。
- [x] `git status --short --branch` — 本任务和前一项尚未提交的 Codex 默认配置改动仍在工作树；另有外部切换的 `refactor/frontend-design` 与无关 `design-previews/`，均保持不动。

## Remaining work

- 无。

## Resume instructions

任务已完成。未来启用向量检索时显式设置 `RAG_RETRIEVAL_MODE=vector`，同时保留默认 lexical 测试与 vector 失败降级测试；不要让向量库是否存在隐式改变默认运行路径。

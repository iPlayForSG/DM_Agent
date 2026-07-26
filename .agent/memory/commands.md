# 开发命令

更新时间：2026-07-26。

## 安装与启动

```powershell
# 后端依赖；依据 backend/requirements.txt
python -m pip install -r backend/requirements.txt

# 前端依赖；依据 frontend/package.json
Set-Location frontend
npm install

# Windows 一键启动；依据 start.cmd 和 README.md
Set-Location ..
.\start.cmd
```

`start.cmd` 会选择 Python、探测可用端口、启动 Uvicorn/Vite、写 `backend/runtime-logs/` 和 `frontend/.env.development.local`，并在非 `-ExitOnReady` 模式打开浏览器。

手工启动：

```powershell
Set-Location backend
python -m uvicorn main:app --host 127.0.0.1 --port 23333 --reload

Set-Location ..\frontend
npm run dev
```

## 验证

先激活已安装 `backend/requirements.txt` 的 Python 环境。当前开发机可使用 `start.cmd` 选择的项目 Conda 环境；不要把开发机绝对路径写进公共文档。

```powershell
# 全量后端测试
python -m unittest discover -s tests -v

# 目标测试示例
python -m unittest tests.test_dm_graph_workflow -v
python -m unittest tests.test_main_streaming -v

# Hook 测试
python -m unittest discover -s .codex/hooks/tests -v

# 前端
Set-Location frontend
npm run build
npm run lint

# 仓库
Set-Location ..
git diff --check
git status --short --branch
```

## 已验证状态

2026-07-26 在当前工作树实际执行：

- 后端 `unittest`：114 tests，成功（项目 Conda 环境）。
- 项目记忆 Hook `unittest`：20 tests，成功。
- `npm run build`：成功。
- `npm run lint`：0 errors、2 warnings；警告位于 `App.jsx` 的 Hook dependency。

当前修改后的 `git diff --check`、手工 Uvicorn、真实 provider 和浏览器长流程尚未完成，不能标为已验证。

## 当前不存在的命令

仓库未定义独立 formatter、Python/JS 类型检查、数据库 migration 或代码生成脚本。新增这些门禁时，应同步 `AGENTS.md`、本文件和相关 CI。

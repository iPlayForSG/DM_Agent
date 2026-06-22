# DM_Agent Frontend

React/Vite 前端应用，负责角色创建、游戏入口、状态展示、聊天交互和最小战斗操作层。

## 运行

```powershell
npm install
npm run dev
```

开发态默认通过 `/api/v1` 访问后端。若存在 `.env.development.local` 中的 `VITE_BACKEND_URL`，则优先直连该后端地址。仓库根目录的 `start.cmd` 会自动写入该配置并启动前后端。

## 构建

```powershell
npm run build
```

## 主要代码

- `src/App.jsx`：主应用和页面状态。
- `src/api.js`：后端 API 调用封装。
- `src/components/`：角色创建、战斗操作、状态展示等组件。
- `src/styles/`：全局样式与页面样式。

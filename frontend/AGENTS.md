# Frontend (lawrag)

基于 Vite + React 19 + TypeScript 的法律智能检索前端。

## 技术栈

- **构建工具**: Vite 8 + `@vitejs/plugin-react`（含 React Compiler preset）
- **框架**: React 19 + react-router / react-router-dom 7/8
- **UI 库**: antd 6 + `@ant-design/icons` + `@ant-design/x` + `@ant-design/x-markdown` + `@ant-design/x-sdk` + `@ant-design/charts` + `@antv/infographic`
- **样式**: `@emotion/react` + `@emotion/styled` + `@emotion/babel-plugin`（`jsxImportSource: "@emotion/react"`）
- **状态管理**: Redux Toolkit + react-redux
- **类型**: TypeScript 7.0.1-rc（`strict: true`，`moduleResolution: "bundler"`）
- **包管理**: pnpm
- **测试**: vitest

## 项目结构

```
frontend/
├── index.html             # 入口 HTML（#root，main.tsx）
├── vite.config.ts         # base="/webui/"，代理 /api -> FASTAPI_HOST:FASTAPI_PORT
├── biome.json             # 格式化 + Lint 配置
├── tsconfig.json          # 路径别名 @ -> src
└── src/
    ├── main.tsx           # 渲染入口（Provider / ConfigProvider / BrowserRouter basename="/webui" / ProtectedRoute）
    ├── App.tsx            # 备用顶层 App（main.tsx 当前为主）
    ├── layouts/           # MainLayout
    ├── pages/             # LoginPage / DashboardPage / ChatPage
    ├── components/        # SuperMarkdown（Markdown + Mermaid + Infographic 渲染）
    ├── api/               # auth / chat / session / types
    ├── store/             # Redux store + slices（authSlice）
    └── utils/             # request.ts (fetch 封装) / navigateRef.ts (非组件内跳转桥接)
```

Vite 把构建产物以 `base: "/webui/"` 输出，本地开发时通过 `/api` 代理访问后端；
构建后由顶层 `just build-ui` 把 `frontend/dist/` 拷贝到仓库根 `static/`，
由后端 FastAPI 在 `/webui/*` 路径挂载。`react-router` 也使用 `basename="/webui"` 对齐。

## 开发命令

```bash
cd frontend

pnpm install
pnpm dev                  # vite 开发服务器（代理 /api -> 后端）
pnpm build                # 输出到 dist/
pnpm preview              # 预览构建产物
pnpm check                # biome check --write（lint + format）
pnpm format               # biome format --write
pnpm lint                 # biome lint --write
pnpm type-check           # tsc --noEmit
pnpm test                 # vitest
```

顶层便捷命令：`just ui` / `just build-ui`（构建后拷贝到 `../static`，由后端 FastAPI 挂载）。

## 环境变量

Vite 通过 `vite.config.ts` 从仓库根 `.env` 读取（与 `lawrag/utils/environments.py` 一致）：

- `FASTAPI_HOST`（默认 `127.0.0.1`）
- `FASTAPI_PORT`（默认 `40001`）

用于 `/api` 代理；浏览器请求直接打到 `http://${host}:${port}`。

## 路径别名

`@/*` -> `./src/*`（`tsconfig.json` 与 `vite.config.ts` 的 `resolve.alias` 均配置）。

## 代码规范

- 缩进 2 空格，LF，行宽 120，双引号。
- Lint / 格式化统一使用 Biome（`pnpm check --write`）。
- Biome 启用：`recommended` + `nursery` + `security` + `performance` + `correctness` + `style` + `complexity` + `suspicious` + `a11y`。
- Biome 排除：`node_modules` / `dist` / `.vite` / `src/auto-imports.d.ts` / `src/components.d.ts` / `src/icons.d.ts`。
- TypeScript 严格模式，类型问题通过 `pnpm type-check` 验证。
- 样式统一走 Emotion，禁止新增 Tailwind / styled-components。
- 鉴权：使用 `localStorage` 中的 `token`，由 `src/utils/request.ts` 统一附加 `Authorization: Bearer ...`，401 自动跳转登录。
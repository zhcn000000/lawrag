# LawRAG workspace

本仓库实现法律法规智能问答系统：`llmserver` 提供模型后端，`backend` 提供 RAG + Agent + API，`frontend` 提供 Web UI。

## 模块导览

- `llmserver/`：Python 3.14 + vLLM 多模型推理服务，暴露 OpenAI 兼容 `/v1` 接口。
- `backend/`：Python 3.14 FastAPI + pydantic-ai 法律 RAG 系统，使用 PostgreSQL + pgvector/vchord_bm25。
- `frontend/`：Vite 8 + React 19 + TypeScript 前端，由 FastAPI 挂载到 `/webui/*`。
- `docker/`：数据库 / llmserver / web 服务的 podman-compose 配置。
- `examples/`：课程提交版产物：`case.json` (100 条问答样本)、`laws.tar.gz` (爬虫抓取的法律/宪法原文)、`report.json` (100 条问答评测结果)。
- `static/`：`just build-ui` 把 `frontend/dist/` 拷贝到这里，由 FastAPI 在 `/webui/*` 挂载。

进入子目录前先阅读对应的 `AGENTS.md`：

- `backend/AGENTS.md`
- `frontend/AGENTS.md`
- `llmserver/AGENTS.md`

## 架构约定

- 模型链路固定走自托管 OpenAI 兼容 vLLM 端点，不再回退到 DSAPI/DeepSeek。
- `LLM_LINK` 由根目录 `.env` 中的 `LLM_PROTOCOL/LLM_HOST/LLM_PORT` 派生，供 chat、embedding、rerank 共用。
- 后端默认模型 ID：`qwen3.5`（chat/agent）；嵌入模型 ID：`qwen3-embedding`；重排模型 ID：`qwen3-reranker`。
- `llmserver/model_launch.json` 必须与上述模型 ID 对齐。
- 根目录 `.env` 会被 backend、frontend、llmserver 共同读取；`find_project_directory()` 沿父目录向上找 `.proj_root` 标记并 `os.chdir`。
- 所有 Python 子模块共享 `httpx2`（`httpx` 的积极维护分支），`lawrag/__init__.py` 已把 `httpx2` 别名为 `httpx`。

## 常用命令

### 模型后端

```bash
just llmserver            # 等价于 cd llmserver && uv run llmserver start
# 也可手动：
cd llmserver
uv sync
uv run llmserver start --config-path llmserver/model_launch.json --host 0.0.0.0 --port 10001
```

`llmserver` 启动时会把工作目录切到仓库根，因此配置路径请使用 `llmserver/model_launch.json`。

### 后端 / 数据 / 评测

```bash
just initdb               # 装扩展 + 创建默认账号 admin/admin
just web                  # 启动 FastAPI (uvicorn 5 workers)
just spider-crawl         # NPC 数据库索引 → law_index 表
just spider-download      # 下载 docx 并解析, raw/structured 写回 law_index 表
just pageindex-import     # law_index.structured → law_nodes
just pageindex-embed      # 把法条分块并嵌入到 documents 表 (最耗时)
just eval [LIMIT]         # 跑内置评测, 报告默认写到 lawrag_eval_report.json
just search QUERY [LIMIT] # 走混合检索 CLI
```

### 前端

```bash
just ui                   # Vite 开发服务器 (代理 /api -> 后端)
just build-ui             # 前端 build + 拷贝到 ./static/
```

### 质量检查

```bash
just backend-format       # cd backend && uv run ruff format
just backend-lint         # cd backend && uv run ruff check --fix
just backend-typecheck    # cd backend && uv run ty check --fix
just frontend-check       # cd frontend && pnpm check (biome)
just frontend-typecheck   # cd frontend && pnpm type-check
```

`llmserver` 检查命令：

```bash
cd llmserver
uv run ruff format
uv run ruff check --fix
uv run ty check --fix
uv run pytest
```

## 修改准则

- 优先复用现有模块和模式，避免新增抽象或依赖。
- 不要手动编辑锁文件来声明依赖；Python 用 `uv add`，前端用 `pnpm add`。
- 不要提交 `.venv/`、`.ruff_cache/`、`node_modules/`、`dist/`、运行日志或临时文件。
- 不要把密钥、token、真实账号密码写入代码、日志、文档或测试数据。
- 不要修改 `examples/` 中的产物，除非任务明确要求更新数据或评测结果。
- 修改项目结构、启动方式、环境变量或评测路径时，同步更新 README 和相关 `AGENTS.md`。

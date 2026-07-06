# Backend (lawrag)

Python 3.14 后端，基于 FastAPI + pydantic-ai 的法律 RAG 系统。

## 技术栈

- **运行时**: Python >= 3.14, < 3.15
- **Web 框架**: FastAPI + uvicorn (5 workers, uvloop)
- **AI 编排**: pydantic-ai (默认模型 deepseek-v4-flash)
- **数据库**: PostgreSQL + pgvector (SQLAlchemy/SQLModel 异步)
- **CLI**: typer (入口 `lawrag`，定义在 `lawrag/__main__.py:42`)
- **MCP**: fastmcp 挂在 `/mcp` 路径
- **文档解析**: lxml, beautifulsoup4, markitdown
- **NLP**: spacy + zh_core_web_trf
- **检索/嵌入**: openai, exa-py, numpy/pandas/scipy, mmh3

## 项目结构

```
backend/
├── lawrag/
│   ├── __main__.py        # CLI 入口 (start/database/search/ingest/pageindex)
│   ├── routers/           # FastAPI 路由 (chat, rag, user, schema)
│   ├── chat/              # pydantic-ai Agent 与 toolsets (rag/code/web)
│   ├── database/          # SQLModel 表与存储 (DocumentStore, RAGMode, LawPageIndex, HistoryStore, UserManager)
│   ├── documents/         # 解析、切分、嵌入 (lawparser, embedder, splitter, tokenizer, converter)
│   ├── tools/             # MCP 与 Tool 基础类
│   └── utils/             # environments.py 加载 .env/.proj_root
├── tests/                 # pytest (asyncio_mode=auto)
└── pyproject.toml
```

## 包管理与开发命令

使用 `uv` 管理依赖（中国科大 PyPI 镜像 + NJU PyTorch 镜像）：

```bash
cd backend

uv sync                                # 安装依赖
uv add <pkg>                           # 添加运行时依赖
uv add --dev <pkg>                     # 添加开发依赖
uv run lawrag <cmd>                    # 运行 CLI（通过 project.scripts 注入）
uv run pytest                          # 运行测试
uv run pytest -m "not db"              # 跳过需要真实数据库的测试
```

CLI 子命令（`lawrag`）：
- `start`：启动 FastAPI 服务（worker=5，uvloop，rich 日志）
- `database init|reset|clean [-d DB]`
- `search <query> [-k N] [-p PAGE]`
- `ingest dir <DIR> [-c CATEGORY] [-s CHUNK_SIZE] [-o CHUNK_OVERLAP]`
- `ingest file <PATH> [-c CATEGORY]`
- `pageindex import|list|show|search|embed`

顶层便捷命令（仓库根目录 `justfile`）：`just web` / `just initdb` / `just ingest-dir`。

## 配置

通过根目录 `.env` 加载（`lawrag/utils/environments.py` 自动向上查找 `.proj_root`）：

| 变量 | 别名 | 默认 |
| --- | --- | --- |
| `FASTAPI_HOST` / `FASTAPI_PORT` | – | `127.0.0.1` / `40001` |
| `POSTGRES_HOST/PORT/USER/DB/PASSWORD` | – | 本地 `127.0.0.1:10004/data` |
| `POSTGRES_DSN` | – | 派生 |
| `RAG_DATA_ROOT` | – | `<proj>/data` |
| `RAG_UUID_SEED` | – | 固定 UUID |
| `RAG_RELEASE_MODE` | – | `True` |
| `RAG_TMP_DIR` | – | `mkdtemp()` |
| `RAG_TOKEN_EXPIRES_IN` | – | `21600` |
| `JWT_SECRET` | – | 默认值，生产必须改 |
| `SSL_KEY_PATH` / `SSL_CERT_PATH` | – | 可选 HTTPS |
| `DEEPSEEK_API_KEY` | – | 缺失时 Agent 无法工作 |

## 代码规范

- 行宽 120，缩进 4 空格，LF，双引号。
- 格式化 / Lint：`uv run ruff format` / `uv run ruff check --fix`。
- 类型检查：`uv run ty check --fix`（Python LSP 使用 ty + ruff）。
- 类型抑制：`# type: ignore` 或 `# type: ignore[error[xxx]]`。
- Python 3.14 语法：无需 `from __future__ import annotations`，`except` 多个异常可直接用逗号。
- 启用的 ruff 规则集：`F/E/W/I/N/FAST/PL/UP/NPY/PD/ASYNC/B/C4/FURB/PTH`（开启 preview）。
- 忽略：`PLR/PLC0415/PLW0603/PLW3201/PLW0717/ASYNC119`。
- 异步 I/O：禁止阻塞调用（`path.read_text` 等已在源头标注 `noqa: ASYNC240`）。

## 测试

- `pytest` + `pytest-asyncio`（`asyncio_mode = "auto"`，`log_cli = true`）。
- 数据库 marker：`@pytest.mark.db` 表示需要真实 PostgreSQL。
- 测试样例位于 `tests/`，已覆盖 `lawparser` 与 `pageindex`。

## 构建产物

`uv_build` 后端，包名 `lawrag`，CLI 入口 `lawrag.__main__:main`。
Docker 镜像：`docker/web/Dockerfile`，端口 `40001 -> 8080`。
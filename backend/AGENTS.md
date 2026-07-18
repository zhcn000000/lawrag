# Backend (lawrag)

Python 3.14 后端，基于 FastAPI + pydantic-ai 的法律 RAG 系统。

## 技术栈

- **运行时**: Python >= 3.14, < 3.15
- **Web 框架**: FastAPI + uvicorn (5 workers, uvloop)
- **AI 编排**: pydantic-ai；固定使用自托管 OpenAI 兼容 vLLM (`chat/model.py` 中 `VLLMChatModel` + `VLLMProvider`，默认 `qwen3.5`)，通过 `.env` 中 `LLM_PROTOCOL/LLM_HOST/LLM_PORT` 拼出 `LLM_LINK`；不再回退到 DSAPI/DeepSeek。`chat/agent.py:15` 从 `chat.model.get_model()` 取得模型
- **嵌入/重排**: `qwen3-embedding` (4096 维) + `qwen3-reranker`，统一通过同一个 OpenAI 兼容端点 `LLM_LINK`，路径 `/v1/embed` 与 `/v1/rerank`。`chat/model.py:157/200` 的 `aembed_documents` / `arerank_documents` 用 `settings.LLM_LINK` 拼接 URL，与 chat 模型共用同一部署
- **数据库**: PostgreSQL 18 + `pgvector` (`vector/halfvec/sparsevec/bit/hstore`) + `vchord` / `vchord_bm25` 提供向量 + BM25 索引；SQLAlchemy/SQLModel 异步
- **CLI**: typer（入口 `lawrag`）
- **爬虫**: scrapy (AsyncCrawlerRunner, 无 Twisted reactor) + selenium (可选) 抓取 NPC 法律法规数据库
- **文档解析**: lxml, beautifulsoup4, markitdown（docx/html → markdown）
- **NLP**: spacy + zh_core_web_trf（句切分 / BM25 分词）
- **BM25**: mmh3 哈希到 1_000_000 词表 + `vchord_bm25` 索引 + RRF 融合
- **代码沙盒**: pydantic-monty（受限 Python REPL）
- **Web 搜索**: exa-py（`search_web`）+ httpx2 + BeautifulSoup（`fetch_web`）
- **鉴权**: pyjwt (HS256) + PostgreSQL `crypt()/gen_salt('bf')` 存密码哈希
- **评估**: pydantic-evals + LLMJudge（测试样本从 `examples/case.json` 读取，默认 100 条）
- **前端资源**: FastAPI 把仓库根 `static/`（由 `just build-ui` 产出）挂载到 `/webui/*`
- **httpx2 共享层**: `lawrag/__init__.py` 把 `httpx2` 别名为 `httpx`，上游仍可 `import httpx`

## 项目结构

```
backend/
├── lawrag/
│   ├── __init__.py            # 把 httpx2 别名为 httpx (兼容 import httpx)
│   ├── __main__.py            # CLI 入口 (start / cli / search / eval / database / spider / pageindex)
│   ├── routers/
│   │   ├── __init__.py        # FastAPI app + /api/login /register /refresh /me + /webui/* 静态挂载
│   │   ├── chat.py            # 流式 SSE chat (/api/chat/{session_id}/stream), 历史/会话/标题
│   │   ├── rag.py             # /api/rag/search 与 /api/rag/pageindex/* REST 接口
│   │   ├── kb.py              # /api/kb/* 知识库管理 (admin-only, 后台任务跑 spider/import/embed)
│   │   ├── eval.py            # /api/eval/run + /api/eval/run-stream 评测 API
│   │   ├── user.py            # /api/users CRUD + 鉴权依赖 (CurrentUserDep / AdminUserDep)
│   │   └── schema.py          # 所有 Pydantic 请求/响应模型
│   ├── chat/
│   │   ├── agent.py           # pydantic-ai Agent 装配 (VLLMChatModel + 4 capabilities) + get_model_settings
│   │   ├── model.py           # VLLMChatModel / VLLMProvider / aembed_documents / arerank_documents
│   │   ├── struct.py          # ModelDeps (select_toolset) + TOOL_REGISTRY + SUBAGENT_REGISTRY
│   │   ├── rag_tools.py       # rag_capability: find_laws / search_documents / get_article_by_path / get_law_articles / get_law_toc / browse_law
│   │   ├── code_tools.py      # code_capability: python_repl (pydantic-monty)
│   │   ├── web_tools.py       # web_capability: search_web (exa) / fetch_web (httpx2 + bs4, 含 SSRF 防护)
│   │   └── subagent_tools.py  # subagent_capability: 调度 explore_agent / general_agent
│   ├── eval/                  # 评测：pydantic-evals + LLMJudge，样本从 examples/case.json 读取
│   │   ├── dataset.py         #   get_dataset + evaluators + LawRagCase/Report/Failure 数据模型
│   │   └── eval.py            #   evaluate() + evaluate_stream() (teardown 写流式结果)
│   ├── database/
│   │   ├── __init__.py        # 导出 UserManager / init_db / reset_db / clean_db
│   │   ├── database.py        # DatabaseManager (asession/acursor/aengine)
│   │   ├── pool.py            # ConnectionPoolManager (psycopg 同步+异步池)
│   │   ├── types.py           # BM25Vector / BM25Loader / BM25Dumper / Password
│   │   ├── tables.py          # SQLModel 表: User / SessionTable / HistoryTable / LawNode / DocumentTable / LawIndexTable
│   │   ├── initdb.py          # 创建扩展 (pgcrypto/vchord/vchord_bm25) + 默认 admin 账号
│   │   ├── pageindex.py       # LawPageIndex: 法律结构树 (law/preamble/part/subpart/chapter/section/article) 导入与查询
│   │   ├── ragsearch.py       # RAGSearch: 向量+BM25 混合检索 (RRF) + rerank + 多级 page index 面包屑
│   │   ├── document.py        # DocumentStore: law_nodes → 分块 → 嵌入 → 写 documents 表
│   │   ├── history.py         # HistoryStore: 会话 + pydantic-ai ModelMessage 持久化
│   │   ├── law_index.py       # LawIndexManager: 法律法规索引元数据 CRUD (law_id, law_name, law_type, raw, structured…)
│   │   └── user.py            # UserManager: JWT 签发/校验 + 用户 CRUD
│   ├── documents/
│   │   ├── models.py          # Document (pydantic) + get_nlp() 单例
│   │   ├── lawparser.py       # cn_to_int / parse_multi_level / flatten_hierarchy / has_parsed_content
│   │   ├── nlp.py             # asplit_document (spacy 句切分 + token overlap) / atokenize_documents (mmh3 → BM25 词频 Counter)
│   │   └── converter.py       # markitdown wrapper (file/url/data-uri)
│   ├── spider/
│   │   ├── law_spider.py      # LawIndexSpider: NPC /law-search/search/list 翻页
│   │   ├── content_spider.py  # ContentDownloadSpider: 签名 URL → docx 下载
│   │   ├── runner.py          # AsyncCrawlerRunner 入口 (run_law_index_spider / run_content_download)
│   │   ├── pipelines.py       # LawIndexPipeline, ContentDownloadPipeline (markitdown → parse_multi_level → json.dumps)
│   │   └── items.py           # LawIndexItem / LawDownloadItem
│   └── environments.py        # pydantic-settings 配置 + 自动向上查找 .proj_root
├── tests/
│   ├── conftest.py            # anyio_backend=asyncio
│   ├── test_lawparser.py      # 离线: cn_to_int / flatten_hierarchy / parse_multi_level / TOC
│   ├── test_document.py       # 离线: DocumentStore / Embedder / splitter
│   ├── test_eval.py           # 离线: eval 数据模型
│   ├── test_rag.py            # 离线: search API 请求校验
│   ├── test_pageindex.py      # @pytest.mark.db 真实数据库 import/list/get/search/toc/delete
│   ├── test_law_index.py      # @pytest.mark.db law_index CRUD
│   └── test_user_auth.py      # @pytest.mark.db JWT 签发/校验 + 用户 CRUD
├── pyproject.toml
└── uv.lock
```

法律索引、原始文本与结构化层级数据均存入 PostgreSQL `law_index` 表。

仓库根 `examples/report.json` 是课程提交版 100 条问答评测结果。

## 包管理与开发命令

使用 `uv` 管理依赖（中国科大 PyPI 镜像 + NJU PyTorch 镜像，spaCy 中文模型走 GitHub 直链）：

```bash
cd backend

uv sync                                # 安装依赖
uv add <pkg>                           # 添加运行时依赖
uv add --dev <pkg>                     # 添加开发依赖
uv run lawrag <cmd>                    # 运行 CLI（通过 project.scripts 注入）
uv run pytest                          # 运行测试
uv run pytest -m "not db"              # 跳过需要真实数据库的测试
uv run pytest -m "db"                  # 仅运行数据库测试
```

CLI 子命令（`uv run lawrag`，入口 `lawrag.__main__:main`）：

顶层：

- `start` — uvicorn 启动 FastAPI（5 workers，HTTPS 可选，加载 `.env` 解析 `SSL_KEY_PATH`/`SSL_CERT_PATH`）。
- `cli [-t TOOLSET...]` — 启动交互式命令行（pydantic-ai `to_cli`）。默认四个工具集全开，可用 `-t rag_toolkit,code_toolkit,web_toolkit,subagent_toolkit` 子集。
- `search <query> [-l LAW] [-r REGEX] [-k N] [-v VEC_WEIGHT]` — 走 `RAGSearch.ahyprid_search` 的混合检索，结果用 rich 表格展示 score/title/content。`-v` (0~1) 调节向量/BM25 权重，默认 0.6。
- `eval [-i INPUT] [-o OUTPUT] [-s START] [-e/-n END] [-f OFFLINE]` — 跑法律问答评测：读 `-i` (默认 `<proj>/examples/case.json`) 的样本，逐条调用 Agent (默认带 rag+web+subagent，禁用 code；`-f` 进一步禁 web)，用 LLMJudge 打分并把 `LawRagCaseReport`/`LawRagCaseFailure` 写到 `-o` (默认 `<cwd>/lawrag_eval_report.json`)。

`database init|reset|clean [-d DB]` — 创建/重置/删除数据库。

- `init` 安装扩展 `pgcrypto`、`vchord`、`vchord_bm25`；创建默认账号 `admin/admin`。

`spider crawl` — NPC 法律法规库索引爬虫：

- `-c` 分类：`xf`(宪法) / `flfg`(法律) / `xzfg`(行政法规) / `jcfg`(监察法规) / `sfjs`(司法解释) / `dfxfg`(地方性法规) / `all`（不含 dfxfg）。
- Stage 1：调用 `/law-search/search/list` JSON API 翻页，条目直接写入 `law_index` 表。
- 宪法仅保留最新版（2018 年修正文本），自动更名为"中华人民共和国宪法"。

`spider download` — 下载+解析：

- 从 `law_index` 表读取待下载候选 (`status=有效`, `law_type in (宪法,法律)`, `raw IS NULL`)，调用 `/law-search/download/pc` 获取签名 URL → 下载 docx → markitdown → `parse_multi_level`，结果 `raw` 文本和 `structured` JSONB 写回 `law_index` 表。

`pageindex convert [-r RAW_DIR] [-o OUTPUT_DIR] [-f FILTER]` — 重新解析 raw 文本生成 structured 数据。

- 默认从 `law_index.raw` 列读取文本，解析后写回 `law_index.structured`。
- 指定 `--raw-dir`/`--output-dir` 时回退到文件模式（`<DATA_ROOT>/raw_laws` → `<DATA_ROOT>/structured_laws`）。

`pageindex import [-l LAW_NAME]` — 把层级结构数据导入 `law_nodes`。

- 默认从 `law_index.structured` 列读取并导入，可选 `-l` 按名称过滤。
- `(law_name, path)` 唯一键保证幂等。

`pageindex list|show|toc|embed` — 法条浏览/嵌入：

- `list` — 列出已导入法律及法条数量。
- `show <law_name> [-s START] [-e END] [-l LIMIT]` — 按条号范围展示法条内容。
- `toc <law_name>` — 编/分编/章/节目录树。
- `embed [law_name] [-s CHUNK_SIZE] [-o CHUNK_OVERLAP] [-b BATCH_SIZE]` — 走 `LawPageIndex` → `DocumentStore.abatch_load_from_texts`。

仓库根目录 `justfile` 一键命令：`just web` / `just initdb` / `just eval` / `just backend-format|lint|typecheck` 等（详见仓库根 `justfile`）。

## 配置

通过 `<repo>/.env` 加载（`lawrag/environments.py` 自动向上查找 `.proj_root`）；环境变量别名使用 `Annotated[..., Field(alias=...)]`：

| 变量                                                  | alias           | 默认                                                                                                                                     |
| ----------------------------------------------------- | --------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `FASTAPI_HOST` / `FASTAPI_PORT`                       | –               | `127.0.0.1` / `40001`                                                                                                                    |
| `POSTGRES_HOST` / `POSTGRES_PORT`                     | –               | `127.0.0.1` / `10004`                                                                                                                    |
| `POSTGRES_USER` / `POSTGRES_DB` / `POSTGRES_PASSWORD` | –               | `postgres` / `data` / `postgres_password`                                                                                                |
| `POSTGRES_DSN`                                        | –               | 由上述字段派生 (`postgresql+psycopg://...`)                                                                                              |
| `DATA_ROOT`                                           | `LAWRAG_DATA_ROOT` (`RAG_DATA_ROOT` 兼容) | `<proj>/data`                                                                                                                            |
| `UUID_SEED`                                           | `LAWRAG_UUID_SEED` (`RAG_UUID_SEED` 兼容) | 固定 UUID `11fa063e-...`                                                                                                                 |
| `RELEASE_MODE`                                        | `RAG_RELEASE_MODE` | `True`（False 时启动会发警告）                                                                                                         |
| `TMP_DIR`                                             | `RAG_TMP_DIR`   | `mkdtemp()`                                                                                                                              |
| `TOKEN_EXPIRES_IN`                                    | `RAG_TOKEN_EXPIRES_IN` | `21600`（秒，6 小时）                                                                                                              |
| `JWT_SECRET`                                          | –               | 默认值，生产必须改                                                                                                                       |
| `SSL_KEY_PATH` / `SSL_CERT_PATH`                      | –               | 可选 HTTPS                                                                                                                               |
| `LLM_PROTOCOL` / `LLM_HOST` / `LLM_PORT`              | –               | `http` / `127.0.0.1` / `40002`；拼接成 `LLM_LINK = <scheme>://<host>:<port>/v1`，供 `chat/model.py` 的 chat/embed/rerank 复用             |
| `LLM_API_KEY`                                         | –               | `SecretStr("sk-")` 兼容 OpenAI SDK                                                                                                       |
| `LLM_LINK`                                            | –               | computed，由上面三个变量派生 (`HttpUrl`)，含尾随 `/v1`                                                                                   |
| `LOG_LEVEL`                                           | –               | `INFO`                                                                                                                                   |

`find_project_directory()` 会沿父目录向上寻找 `.proj_root` 标记文件；找到后 `os.chdir` 至该目录，确保数据库脚本与相对路径一致。

## API 路由一览

按职责划分到 6 个 Router (`lawrag/routers/`)：

| 路径                          | router                  | 说明                                                           |
| ----------------------------- | ----------------------- | -------------------------------------------------------------- |
| `POST /api/login`             | `routers/__init__.py`   | 用户名密码登录，写 `lawrag_token` HttpOnly cookie + 返回 token |
| `POST /api/register`          | `routers/__init__.py`   | 用户注册 (admin-only)                                          |
| `POST /api/refresh`           | `routers/__init__.py`   | 刷新 JWT                                                       |
| `GET  /api/me`                | `routers/__init__.py`   | 获取当前用户信息                                               |
| `/api/users/*`                | `routers/user.py`       | 用户 CRUD                                                      |
| `/api/chat/*`                 | `routers/chat.py`       | 会话/历史/SSE 流式 chat                                        |
| `/api/rag/*`                  | `routers/rag.py`        | 混合检索 + page index 入口                                     |
| `/api/kb/*`                   | `routers/kb.py`         | 知识库管理 (admin-only，后台任务跑 crawl/download/embed)       |
| `/api/eval/run` `/run-stream` | `routers/eval.py`       | 评测 (pydantic-evals + LLMJudge)                               |
| `/webui/*`                    | `routers/__init__.py`   | 挂载仓库根 `static/` (由 `just build-ui` 产出)                 |

## 代码规范

- 行宽 120，缩进 4 空格，LF，双引号。
- 格式化 / Lint：`uv run ruff format` / `uv run ruff check --fix`。
- 类型检查：`uv run ty check --fix`（Python LSP 使用 ty + ruff）。
- 类型抑制：`# type: ignore` 或 `# type: ignore[error[xxx]]`。
- Python 3.14 语法：无需 `from __future__ import annotations`，`except` 多个异常可直接用逗号。
- 启用的 ruff 规则集：`F/E/W/I/N/FAST/PL/UP/NPY/PD/ASYNC/B/C4/FURB/PATH`（开启 preview）。
- 忽略：`import-outside-top-level`、`global-statement`、`bad-dunder-method-name`、`too-many-statements-in-try-clause`、全部 `PLR*`。
- 路由使用 RESTful 风格，`lawrag/routers/schema.py` 定义所有请求/响应模型。需要添加合适的权限系统
- `httpx2` 是 `httpx` 的兼容api，作为积极维护的分支，原本从 `httpx` 导入可直接改为从 `httpx2` 导入；`lawrag/__init__.py` 已经统一为 `import httpx`

## 测试

- `pytest` + `pytest-asyncio`（`asyncio_mode = "auto"`，`log_cli = true`，`log_cli_level = "INFO"`）。
- 数据库 marker：`@pytest.mark.db` 表示需要真实 PostgreSQL（含 `pgcrypto`/`vchord`/`vchord_bm25`）。
- `tests/conftest.py` 提供 `anyio_backend = "asyncio"`。
- 测试样例位于 `tests/`，已覆盖 `lawparser` / `document` / `eval` / `rag` (离线) 与 `pageindex` / `law_index` / `user_auth` (在线)。

## 构建产物

- `uv_build` 后端，包名 `lawrag`，CLI 入口 `lawrag.__main__:main`，见 `pyproject.toml:44-45`。
- 前端构建产物由 FastAPI 在 `/webui/*` 路径直接挂载（仓库根 `static/` 目录，`routers/__init__.py:31-49`）。如未构建会返回 404。
- Docker 镜像：`docker/web/Dockerfile` 与 `docker-compose.yaml`，`web` 服务端口 `40001 -> 8080`、`llmserver` 服务端口 `40003 -> 8080`、`database` 服务端口 `40002 -> 5432`；都用 `app-network` 互联，web 同时挂载 `web-volume -> /app/data`。
- 数据库镜像：`docker-compose.yaml` 中 `database` 服务使用 `localhost/postgres-age:latest`（PostgreSQL 18 + `pgcrypto` + `vchord` + `vchord_bm25`）。
- 顶层 `just docker` 同时拉起 web / llmserver / database（`podman-compose up`）。

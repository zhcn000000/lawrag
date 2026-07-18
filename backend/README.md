# Backend · lawrag

Python 3.14 后端，基于 FastAPI + pydantic-ai 的法律法规 RAG 问答系统：提供爬虫、文档解析、混合检索、多工具 Agent、鉴权、评测与 REST/SSE 接口。

## 技术栈

- **运行时**: Python `>= 3.14, < 3.15`，用 [uv](https://docs.astral.sh/uv/) 管理依赖
- **Web 框架**: FastAPI + uvicorn（5 workers，uvloop）
- **AI 编排**: pydantic-ai，固定走自托管 OpenAI 兼容 vLLM 端点（`chat/model.py` 中 `VLLMChatModel` + `VLLMProvider`，默认 `qwen3.5`），通过 `.env` 的 `LLM_PROTOCOL/LLM_HOST/LLM_PORT` 拼出 `LLM_LINK`，不再回退 DSAPI/DeepSeek
- **嵌入 / 重排**: `qwen3-embedding`（4096 维）+ `qwen3-reranker`，与 chat 共用同一个 `LLM_LINK`，路径 `/v1/embed` 与 `/v1/rerank`
- **数据库**: PostgreSQL 18 + `pgvector`（`vector/halfvec/sparsevec/bit/hstore`）+ `vchord` / `vchord_bm25`（向量 + BM25），SQLModel/SQLAlchemy 异步
- **CLI**: typer（入口 `lawrag`）
- **爬虫**: scrapy（`AsyncCrawlerRunner`，无 Twisted reactor）+ selenium（可选），抓取全国人大法律法规数据库
- **文档解析**: lxml、beautifulsoup4、markitdown（docx/html → markdown）
- **NLP / BM25**: spaCy + `zh_core_web_trf` 句切分；mmh3 哈希到 1_000_000 词表 + `vchord_bm25` 索引 + RRF 融合
- **代码沙盒**: pydantic-monty（受限 Python REPL）
- **Web 搜索**: exa-py（`search_web`）+ httpx2 + BeautifulSoup（`fetch_web`）
- **鉴权**: pyjwt (HS256) + PostgreSQL `crypt()/gen_salt('bf')` 存密码哈希
- **评估**: pydantic-evals + LLMJudge（样本从 `examples/case.json` 读取，默认 100 条）
- **前端资源**: FastAPI 把仓库根 `static/`（`just build-ui` 产出）挂载到 `/webui/*`
- **httpx2 共享层**: `lawrag/__init__.py` 把 `httpx2` 别名为 `httpx`，上游仍可用 `import httpx`

## 项目结构

```
backend/
├── lawrag/
│   ├── __init__.py            # 把 httpx2 别名为 httpx (兼容 import httpx)
│   ├── __main__.py            # CLI 入口 (start / cli / search / eval / database / spider / pageindex)
│   ├── routers/
│   │   ├── __init__.py        # FastAPI app + /api/login/register/refresh/me + /webui/* 静态挂载
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
│   ├── eval/                  # 评测：pydantic-evals + LLMJudge, 样本从 examples/case.json 读取
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
│   │   ├── law_index.py       # LawIndexManager: 法律法规索引元数据 CRUD (raw / structured)
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

仓库根 `examples/report.json` 是课程提交版 100 条问答评测结果。

## 包管理与开发命令

使用 `uv` 管理依赖（中国科大 PyPI 镜像 + NJU PyTorch 镜像，spaCy 中文模型走 GitHub 直链）：

```bash
cd backend

uv sync                                # 安装依赖
uv add <pkg>                           # 添加运行时依赖
uv add --dev <pkg>                     # 添加开发依赖
uv run lawrag <cmd>                    # 运行 CLI
uv run pytest                          # 运行测试
uv run pytest -m "not db"              # 跳过需要真实数据库的测试
uv run pytest -m "db"                  # 仅运行数据库测试
```

CLI 子命令（`uv run lawrag`，入口 `lawrag.__main__:main`）：

- `start` — uvicorn 启动 FastAPI（5 workers，可选 HTTPS，解析 `SSL_KEY_PATH`/`SSL_CERT_PATH`）。
- `cli [-t TOOLSET...]` — 启动 pydantic-ai 交互式命令行；`-t` 限制工具集（`rag_toolkit`/`code_toolkit`/`web_toolkit`/`subagent_toolkit`）。
- `search <query> [-l LAW] [-r REGEX] [-k N] [-v VEC_WEIGHT]` — 走 `RAGSearch.ahyprid_search` 的混合检索，rich 表格展示 score/title/content，`-v` (0~1) 调节向量/BM25 权重，默认 0.6。
- `database init|reset|clean [-d DB]` — 创建/重置/删除数据库。`init` 安装扩展 `pgcrypto`、`vchord`、`vchord_bm25`，创建默认账号 `admin/admin`。
- `spider crawl [-c CATEGORY]` — NPC 索引爬虫。`-c` 分类：`xf`(宪法) / `flfg`(法律) / `xzfg`(行政法规) / `jcfg`(监察法规) / `sfjs`(司法解释) / `dfxfg`(地方性法规) / `all`（不含 dfxfg）。
- `spider download` — 从 `law_index` 表读取待下载候选，签名 URL → 下载 docx → markitdown → `parse_multi_level` → 写回 law_index。
- `pageindex convert [-r RAW_DIR] [-o OUTPUT_DIR] [-f FILTER]` — 从 `law_index.raw` 重新解析生成 `law_index.structured`；指定 `--raw-dir`/`--output-dir` 时回退到文件模式（`<DATA_ROOT>/raw_laws` → `<DATA_ROOT>/structured_laws`）。
- `pageindex import [-l LAW_NAME]` — 把 `law_index.structured` 导入 `law_nodes`；`(law_name, path)` 唯一键保证幂等。
- `pageindex list|show|toc|embed [law_name]` — 法条浏览/嵌入，`embed` 走 `LawPageIndex` → `DocumentStore.abatch_load_from_texts`。
- `eval [-i INPUT] [-o OUTPUT] [-s START] [-e/-n END] [-f OFFLINE]` — 从测试集（`-i`，默认仓库根 `examples/case.json`）读取问答样本，用 Agent 生成答案并与标准答案对比，LLMJudge 打分，结果写入 `-o` (默认 `<cwd>/lawrag_eval_report.json`)。

仓库根 `justfile` 一键命令：`just web` / `just initdb` / `just eval` / `just backend-format|lint|typecheck` 等。

## API 路由一览

| 路径                                | 说明                                                              |
| ----------------------------------- | ----------------------------------------------------------------- |
| `POST /api/login` `POST /api/register` `POST /api/refresh` `GET /api/me` | 鉴权（明文路由见 `routers/__init__.py`） |
| `/api/users/*`                      | 用户 CRUD（基于 `CurrentUserDep`/`AdminUserDep` 守卫）            |
| `/api/chat/*`                       | 流式 SSE chat + 历史/会话/标题                                    |
| `/api/rag/*`                        | 混合检索 + page index REST 接口                                   |
| `/api/kb/*`                         | 知识库管理 (admin-only，crawl/download/import/embed 后台任务)     |
| `/api/eval/run` `/api/eval/run-stream` | 评测 (pydantic-evals + LLMJudge)                               |
| `/webui/*`                          | 挂载仓库根 `static/`（由 `just build-ui` 产出）                   |

## 配置

通过 `<repo>/.env` 加载（`environments.py` 自动向上查找 `.proj_root`）；环境变量别名用 `Annotated[..., Field(alias=...)]`：

| 变量                                                  | alias           | 默认                                                                          |
| ----------------------------------------------------- | --------------- | ----------------------------------------------------------------------------- |
| `FASTAPI_HOST` / `FASTAPI_PORT`                       | –               | `127.0.0.1` / `40001`                                                         |
| `POSTGRES_HOST` / `POSTGRES_PORT`                     | –               | `127.0.0.1` / `10004`                                                         |
| `POSTGRES_USER` / `POSTGRES_DB` / `POSTGRES_PASSWORD` | –               | `postgres` / `data` / `postgres_password`                                     |
| `POSTGRES_DSN`                                        | –               | 由上述字段派生 (`postgresql+psycopg://...`)                                   |
| `DATA_ROOT`                                           | `LAWRAG_DATA_ROOT` (`RAG_DATA_ROOT` 兼容) | `<proj>/data`                                            |
| `UUID_SEED`                                           | `LAWRAG_UUID_SEED` (`RAG_UUID_SEED` 兼容) | 固定 UUID                                            |
| `RELEASE_MODE`                                        | `RAG_RELEASE_MODE` | `True`                                                                      |
| `TMP_DIR`                                             | `RAG_TMP_DIR`   | `mkdtemp()`                                                                   |
| `TOKEN_EXPIRES_IN`                                    | `RAG_TOKEN_EXPIRES_IN` | `21600`（秒，6 小时）                                                  |
| `JWT_SECRET`                                          | –               | 默认值，生产必须改                                                            |
| `SSL_KEY_PATH` / `SSL_CERT_PATH`                      | –               | 可选 HTTPS                                                                    |
| `LLM_PROTOCOL` / `LLM_HOST` / `LLM_PORT`              | –               | `http` / `127.0.0.1` / `40002`；拼成 `LLM_LINK = <scheme>://<host>:<port>/v1` |
| `LLM_API_KEY`                                         | –               | `SecretStr("sk-")` 兼容 OpenAI SDK                                            |
| `LLM_LINK`                                            | –               | computed，由上面三个变量派生，含尾随 `/v1`                                    |
| `LOG_LEVEL`                                           | –               | `INFO`                                                                        |

`find_project_directory()` 沿父目录向上寻找 `.proj_root`，找到后 `os.chdir` 至该目录，确保数据库脚本与相对路径一致。

## 代码规范

- 行宽 120，缩进 4 空格，LF，双引号。
- 格式化 / Lint：`uv run ruff format` / `uv run ruff check --fix`。
- 类型检查：`uv run ty check --fix`（Python LSP 使用 ty + ruff）。
- 类型抑制：`# type: ignore` 或 `# type: ignore[error[xxx]]`。
- Python 3.14 语法：无需 `from __future__ import annotations`，`except` 多个异常可直接用逗号。
- 启用的 ruff 规则集：`F/E/W/I/N/FAST/PL/UP/NPY/PD/ASYNC/B/C4/FURB/PTH`（preview）；忽略 `import-outside-top-level`、`global-statement`、`bad-dunder-method-name`、`too-many-statements-in-try-clause`、全部 `PLR*`。
- 路由使用 RESTful 风格，`lawrag/routers/schema.py` 定义所有请求/响应模型。
- `httpx2` 是 `httpx` 的兼容api，作为积极维护的分支，原本从 `httpx` 导入可直接改为从 `httpx2` 导入；`lawrag/__init__.py` 已统一为 `import httpx`。

## 测试

- `pytest` + `pytest-asyncio`（`asyncio_mode = "auto"`，`log_cli = true`，`log_cli_level = "INFO"`）。
- 数据库 marker：`@pytest.mark.db` 表示需要真实 PostgreSQL（含 `pgcrypto`/`vchord`/`vchord_bm25`）。
- `tests/conftest.py` 提供 `anyio_backend = "asyncio"`。
- 测试样例：
  - 离线：`test_lawparser.py` / `test_document.py` / `test_eval.py` / `test_rag.py`
  - 在线 (`@pytest.mark.db`)：`test_pageindex.py` / `test_law_index.py` / `test_user_auth.py`

## 构建产物

- `uv_build` 后端，包名 `lawrag`，CLI 入口 `lawrag.__main__:main`。
- 前端构建产物由 FastAPI 在 `/webui/*` 挂载（仓库根 `static/` 目录）；未构建返回 404。
- Docker：`docker/web/Dockerfile` + `docker/llmserver/Dockerfile` + `docker/database/Dockerfile`，`web` 端口 `40001 -> 8080`、`llmserver` 端口 `40003 -> 8080`、`database` 端口 `40002 -> 5432`，都用 `app-network` 互联。
- 顶层 `just docker` 同时拉起 web / llmserver / database（`podman-compose up`）。

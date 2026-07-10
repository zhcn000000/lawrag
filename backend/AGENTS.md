# Backend (lawrag)

Python 3.14 后端，基于 FastAPI + pydantic-ai 的法律 RAG 系统。

## 技术栈

- **运行时**: Python >= 3.14, < 3.15
- **Web 框架**: FastAPI + uvicorn (5 workers, uvloop)
- **AI 编排**: pydantic-ai；固定使用自托管 OpenAI 兼容 vLLM (`chat/chat_model.py` 中 `VLLMChatModel` + `VLLMProvider`，默认 `qwen3.5`)，通过 `.env` 中 `LLM_PROTOCOL/LLM_HOST/LLM_PORT` 拼出 `LLM_LINK`；不再回退到 DSAPI/DeepSeek。`chat/model.py:15` 从 `chat_model.get_model()` 取得模型
- **嵌入/重排**: `qwen3-embedding` (4096 维) + `qwen3-reranker`，统一通过同一个 OpenAI 兼容端点 `LLM_LINK`（默认 `http://127.0.0.1:40002/v1`），路径 `/v1/embeddings` 与 `/v1/rerank`。`documents/embedder.py:12` 用 `settings.LLM_LINK` 拼接 URL，与 chat 模型共用同一部署
- **数据库**: PostgreSQL 18 + `pgvector` (`vector/halfvec/sparsevec/bit/hstore`) + `vchord` / `vchord_bm25` 提供向量 + BM25 索引；SQLAlchemy/SQLModel 异步
- **CLI**: typer（入口 `lawrag`）
- **爬虫**: scrapy (AsyncCrawlerRunner, 无 Twisted reactor) + selenium (可选) 抓取 NPC 法律法规数据库
- **文档解析**: lxml, beautifulsoup4, markitdown（docx/html → markdown）
- **NLP**: spacy + zh_core_web_trf（句切分 / BM25 分词）
- **BM25**: mmh3 哈希到 1_000_000 词表 + `vchord_bm25` 索引 + RRF 融合
- **代码沙盒**: pydantic-monty（受限 Python REPL，仅可用 sys/typing/asyncio）
- **Web 搜索**: exa-py（`search_web`）+ httpx + BeautifulSoup（`fetch_web`）
- **鉴权**: pyjwt (HS256) + PostgreSQL `crypt()/gen_salt('bf')` 存密码哈希
- **评估**: pydantic-evals + LLMJudge（测试样本从 `examples/case.json` 读取，默认 100 条）
- **前端资源**: FastAPI 把仓库根 `static/`（由 `just build-ui` 产出）挂载到 `/webui/*`

## 项目结构

```
backend/
├── lawrag/
│   ├── __init__.py            # 重新导出 FastAPI app
│   ├── __main__.py            # CLI 入口 (start / search / database / spider / pageindex / eval)
│   ├── routers/
│   │   ├── __init__.py        # FastAPI app + auth (login/register/refresh/me) + /webui/* 静态挂载
│   │   ├── chat.py            # 流式 SSE chat (/api/chat/{session_id}/stream), 历史/会话/标题
│   │   ├── rag.py             # /api/rag/search 与 /api/rag/pageindex/* REST 接口
│   │   ├── user.py            # /api/users CRUD
│   │   └── schema.py          # 所有 Pydantic 请求/响应模型
│   ├── chat/
│   │   ├── model.py           # pydantic-ai Agent 装配 (VLLMChatModel + toolsets)
│   │   ├── chat_model.py      # 自托管 vLLM 适配层: VLLMChatModel + VLLMProvider + get_model() (默认 qwen3.5)
│   │   ├── struct.py          # ModelDeps (select_toolset)
│   │   ├── rag_tools.py       # rag_toolset: list_laws / search_documents / get_article_by_path / get_law_articles / get_law_toc / browse_law
│   │   ├── code_tools.py      # code_toolset: python_repl (pydantic-monty)
│   │   ├── web_tools.py       # web_toolset: search_web (exa) / fetch_web (httpx + bs4)
│   │   └── subagent_tools.py  # subagent_toolset: subagent 调度 explore_agent / general_agent
│   ├── eval/                  # 评测：pydantic-evals + LLMJudge，样本从 examples/case.json 读取
│   │   ├── dataset.py         #   get_dataset + evaluators + LawRagCase/Report 数据模型
│   │   └── eval.py            #   evaluate(): 跑 Agent + LLMJudge，返回 LawRagCaseReport 列表
│   ├── database/
│   │   ├── __init__.py        # 导出 UserManager / init_db / reset_db / clean_db
│   │   ├── database.py        # DatabaseManager (asession/acursor/aengine)
│   │   ├── pool.py            # ConnectionPoolManager (psycopg 同步+异步池)
│   │   ├── types.py           # BM25Vector / BM25Loader / BM25Dumper / Password
│   │   ├── tables.py          # SQLModel 表: User, SessionTable, HistoryTable, LawNode, DocumentTable
│   │   ├── initdb.py          # 创建扩展 (pgcrypto/vchord/vchord_bm25) + 默认 admin 账号
│   │   ├── pageindex.py       # LawPageIndex: 法律结构树 (law/preamble/part/subpart/chapter/section/article) 导入与查询
│   │   ├── ragmode.py         # RAGMode: 向量+BM25 混合检索 (RRF) + rerank + 多级 page index 面包屑
│   │   ├── document.py        # DocumentStore: 分块 → 嵌入 → 写 documents 表
│   │   ├── history.py         # HistoryStore: 会话 + pydantic-ai ModelMessage 持久化
│   │   └── user.py            # UserManager: JWT 签发/校验 + 用户 CRUD
│   ├── documents/
│   │   ├── models.py          # Document (pydantic) + get_nlp() 单例
│   │   ├── lawparser.py       # cn_to_int / parse_multi_level / flatten_hierarchy
│   │   ├── embedder.py        # aembed_documents / arerank_* (qwen3-embedding/qwen3-reranker)
│   │   ├── splitter.py        # asplit_content (spacy 句切分 + token overlap) / asplit_document
│   │   ├── tokenizer.py       # atokenize_document (mmh3 → BM25 词频 Counter)
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
│   ├── test_lawparser.py      # cn_to_int / flatten_hierarchy / parse_multi_level / TOC
│   └── test_pageindex.py      # @pytest.mark.db 真实数据库 import/list/get/search/toc/delete
├── pyproject.toml
└── uv.lock
```

数据落盘约定（默认位于 `<proj>/data/`，可通过 `LAWRAG_DATA_ROOT` 覆盖）：

```
data/
├── law_index/law_index.json           # spider crawl 产物
├── downloaded_laws/*.docx             # spider download 原始文件
├── raw_laws/<law_name>.txt            # markitdown 转换结果
├── structured_laws/<law_name>.json    # parse_multi_level 输出的 JSON 序列化结果 (pageindex import 输入)
└── eval/report.json                   # eval run 默认输出
```

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
- `search <query> [-k N]` — 走 `RAGMode.ahyprid_search` 的混合检索，结果用 rich 表格展示 score/title/content。

`database init|reset|clean [-d DB]` — 创建/重置/删除数据库。

- `init` 安装扩展 `pgcrypto`、`vchord`、`vchord_bm25`；创建默认账号 `admin/admin`。

`spider crawl` — NPC 法律法规库索引爬虫：

- `-c` 分类：`xf`(宪法) / `flfg`(法律) / `xzfg`(行政法规) / `jcfg`(监察法规) / `sfjs`(司法解释) / `dfxfg`(地方性法规) / `all`（不含 dfxfg）。
- `-o` 输出路径，默认 `<DATA_ROOT>/law_index/law_index.json`。
- Stage 1：只发现条目，调用 `/law-search/search/list` JSON API 翻页。

`spider download [INDEX_PATH]` — 下载+解析：

- `[INDEX_PATH]` 默认 `<DATA_ROOT>/law_index/law_index.json`。
- `-o` 结构化输出目录；`-d` 原始 docx 目录；`-c` 可选分类过滤。
- Stage 2+3：调用 `/law-search/download/pc` 获取签名 URL → 下载 docx → markitdown → `parse_multi_level` → `json.dumps` → `<structured_laws>/.manifest.json`。

`pageindex convert [-r RAW_DIR] [-o OUTPUT_DIR] [-f FILTER]` — 从 `raw_laws/*.txt` 重新解析并生成 `structured_laws/*.json`（无需重新下载）。可选 `-f` 按法律名称过滤。

`pageindex import [PATH] [-c CATEGORY]` — 把 `structured_laws/*.json` 导入 `law_nodes`，默认 `<DATA_ROOT>/structured_laws`。重导前先清空同 `law_name` 的节点，`(law_name, path)` 唯一键保证幂等。

`pageindex list|show|toc|search|embed` — 法条浏览/查询/嵌入：

- `list`
- `show <law_name> [-s START] [-e END] [-l LIMIT]`
- `toc <law_name>`（编/分编/章/节 树）
- `search <law_name> <query> [-l LIMIT]`（按 content ILIKE 过滤；**注意**：`__main__.pageindex_search` 是顶层命令，此处为局部 ILIKE 过滤，名称易混淆）
- `embed [law_name] [-s CHUNK_SIZE] [-o CHUNK_OVERLAP] [-b BATCH_SIZE]`（走 `LawPageIndex.aembed_law_articles` → `DocumentStore.abatch_load_from_texts`）

`eval run [-i INPUT] [-n MAX_CASES] [-o OUTPUT]` — 跑法律问答样本：从 JSON 测试集（`-i`，默认仓库根 `examples/case.json`）读取问答样本，用 Agent 生成答案并与标准答案对比，由 LLMJudge 打分；结果以 rich 表格展示并以 JSON 写入 `<DATA_ROOT>/eval/report.json`。仓库根 `examples/report.json` 保留课程提交版完整结果。默认 100 条以《劳动合同法》为主的样本。

仓库根目录 `justfile` 一键命令：`just web` / `just initdb` / `just eval` / `backend-format|lint|typecheck` 等（详见仓库根 `justfile`）。

## 配置

通过 `<repo>/.env` 加载（`lawrag/utils/environments.py` 自动向上查找 `.proj_root`）；环境变量别名使用 `Annotated[..., Field(alias=...)]`：

| 变量                                                  | alias           | 默认                                                                                                                                     |
| ----------------------------------------------------- | --------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `FASTAPI_HOST` / `FASTAPI_PORT`                       | –               | `127.0.0.1` / `40001`                                                                                                                    |
| `POSTGRES_HOST` / `POSTGRES_PORT`                     | –               | `127.0.0.1` / `10004`                                                                                                                    |
| `POSTGRES_USER` / `POSTGRES_DB` / `POSTGRES_PASSWORD` | –               | `postgres` / `data` / `postgres_password`                                                                                                |
| `POSTGRES_DSN`                                        | –               | 由上述字段派生 (`postgresql+psycopg://...`)                                                                                              |
| `LAWRAG_DATA_ROOT`                                    | `RAG_DATA_ROOT` | `<proj>/data`                                                                                                                            |
| `LAWRAG_UUID_SEED`                                    | `RAG_UUID_SEED` | 固定 UUID `11fa063e-...`                                                                                                                 |
| `RAG_RELEASE_MODE`                                    | –               | `True`（False 时启动会发警告）                                                                                                           |
| `RAG_TMP_DIR`                                         | –               | `mkdtemp()`                                                                                                                              |
| `RAG_TOKEN_EXPIRES_IN`                                | –               | `21600`（秒，6 小时）                                                                                                                    |
| `JWT_SECRET`                                          | –               | 默认值，生产必须改                                                                                                                       |
| `SSL_KEY_PATH` / `SSL_CERT_PATH`                      | –               | 可选 HTTPS                                                                                                                               |
| `LLM_PROTOCOL` / `LLM_HOST` / `LLM_PORT`              | –               | `http` / `127.0.0.1` / `40002`；拼接成 `LLM_LINK = <scheme>://<host>:<port>/v1`，供 `chat/chat_model.py` 与 `documents/embedder.py` 复用 |
| `LLM_LINK`                                            | –               | computed，由上面三个变量派生 (`HttpUrl`)，含尾随 `/v1`                                                                                   |
| `USER_AGENT`                                          | –               | 默认 Chrome UA（覆盖爬虫反爬）                                                                                                           |

`find_project_directory()` 会沿父目录向上寻找 `.proj_root` 标记文件；找到后 `os.chdir` 至该目录，确保数据库脚本与相对路径一致。

## 代码规范

- 行宽 120，缩进 4 空格，LF，双引号。
- 格式化 / Lint：`uv run ruff format` / `uv run ruff check --fix`。
- 类型检查：`uv run ty check --fix`（Python LSP 使用 ty + ruff）。
- 类型抑制：`# type: ignore` 或 `# type: ignore[error[xxx]]`。
- Python 3.14 语法：无需 `from __future__ import annotations`，`except` 多个异常可直接用逗号。
- 启用的 ruff 规则集：`F/E/W/I/N/FAST/PL/UP/NPY/PD/ASYNC/B/C4/FURB/PTH`（开启 preview）。
- 忽略：`PLR/PLC0415/PLW0603/PLW3201/PLW0717`。

## 测试

- `pytest` + `pytest-asyncio`（`asyncio_mode = "auto"`，`log_cli = true`，`log_cli_level = "INFO"`）。
- 数据库 marker：`@pytest.mark.db` 表示需要真实 PostgreSQL（含 `pgcrypto`/`vchord`/`vchord_bm25`）。
- `tests/conftest.py` 提供 `anyio_backend = "asyncio"`。
- 测试样例位于 `tests/`，已覆盖 `lawparser` 与 `pageindex`；其中 `test_lawparser.py` 不依赖数据库，`test_pageindex.py` 需要数据库。

## 构建产物

- `uv_build` 后端，包名 `lawrag`，CLI 入口 `lawrag.__main__:main`，见 `pyproject.toml:44-49`。
- 前端构建产物由 FastAPI 在 `/webui/*` 路径直接挂载（仓库根 `static/` 目录，`routers/__init__.py:26-44`）。如未构建会返回 404。
- Docker 镜像：`docker/web/Dockerfile` 与 `docker-compose.yaml`，`web` 服务端口 `40001 -> 8080`（同时挂载 `web-volume -> /app/data`，与数据库用 `app-network` 互联）。
- 数据库镜像：`docker-compose.yaml` 中 `database` 服务（本地端口 `40002`），使用 `localhost/postgres-age:latest`（PostgreSQL 18 + `pgcrypto` + `vchord` + `vchord_bm25`）。
- 顶层 `just docker` 同时拉起 web 与 database（`podman-compose up`）。

# LawRAG · 基于本地大模型的法律法规智能问答系统

[![Python](https://img.shields.io/badge/Python-3.14-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.119-009688)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61dafb)](https://react.dev/)
[![pydantic--ai](https://img.shields.io/badge/pydantic--ai-2.5-purple)](https://ai.pydantic.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18%2Bpgvector-336791)](https://github.com/pgvector/pgvector)
[![License](https://img.shields.io/badge/license-Internal-lightgrey)](#)

> 本仓库实现课程实习需求《基于本地大语言模型的法律法规智能问答系统构建与 Agent 任务调度实践》。
> 系统以 NPC 法律法规数据库为数据源, 通过爬虫自建法律知识库, 用 RAG + 多工具 Agent 提供多轮法律问答服务, 并内置评估数据集与 LLM 评判链路。

## ✨ 特性

- 📚 **自建法律知识库**: 用 `scrapy` 异步爬虫抓取全国人大法律法规数据库, `markitdown` + `parse_multi_level` 把 docx 转结构化 JSON, 支持宪法/法律/行政法规/监察法规/司法解释五大类;
- 🔍 **混合检索**: 向量 (`qwen3-embedding` 4096 维) + BM25 (`vchord_bm25` + mmh3) 双索引, RRF 融合后用 `qwen3-reranker` 重排, 沿多级 `page index` 拼出面包屑;
- 🤖 **多 Agent 协作**: pydantic-ai 编排 4 个可插拔工具集, 用户可勾选启用:
  - **RAG** —— `list_laws / search_documents / get_article_by_path / get_law_articles / get_law_toc / browse_law`;
  - **Code** —— `python_repl` 基于 pydantic-monty 受限沙箱;
  - **Web** —— `search_web` (exa) + `fetch_web` (httpx + bs4);
  - **Subagent** —— 把任务委派给 `explore_agent`(纯检索) / `general_agent`(全工具);
- 💬 **流式多轮对话**: pydantic-ai `ModelMessage` 完整持久化到 PostgreSQL, 跨会话/重启上下文不丢;
- 🖥️ **可视化前端**: Vite 8 + React 19 + TypeScript 7.0-rc + antd 6 + Emotion + Redux Toolkit, Markdown 内嵌 Mermaid 与 Infographic;
- 📊 **评估闭环**: 内置 100 条以《劳动合同法》为主的问答样本 (满足"每组至少 100 条"要求), 用 pydantic-evals + LLMJudge 跑通并写报告 JSON;
- 🐳 **容器化**: 提供 `podman-compose` 一键拉起 PostgreSQL18 + 应用容器 (本地端口 `40001/40002`).

## 🗂️ 仓库结构

```
lawrag/
├── backend/                # Python 3.14 FastAPI + pydantic-ai 法律 RAG 系统
│   ├── lawrag/
│   │   ├── __main__.py     # CLI 入口 (start/database/search/spider/pageindex/eval)
│   │   ├── routers/        # FastAPI 路由 (auth / chat / rag / users)
│   │   ├── chat/           # Agent 装配 + 4 个 toolset + Subagent
│   │   ├── database/       # pgvector + vchord_bm25 异步 ORM
│   │   ├── documents/      # 切分 / 嵌入 / 重排 / BM25 分词 / docx 转换
│   │   ├── eval/           # 100 条 pydantic-evals Case + LLMJudge
│   │   ├── spider/         # scrapy 异步爬虫 (NPC 数据库)
│   │   └── utils/          # 环境变量 / system prompt
│   ├── tests/              # pytest + pytest-asyncio (db marker 区分是否需要 PostgreSQL)
│   └── pyproject.toml
├── frontend/               # Vite 8 + React 19 + TypeScript 法律智能问答前端
│   ├── src/
│   │   ├── pages/          # LoginPage / DashboardPage / ChatPage
│   │   ├── api/            # auth / chat / session / types
│   │   ├── layouts/        # MainLayout (antd ProLayout 风格)
│   │   ├── components/     # SuperMarkdown (Markdown + Mermaid + Infographic)
│   │   ├── store/          # Redux Toolkit (authSlice)
│   │   └── utils/          # request.ts / navigateRef.ts
│   └── package.json
├── docker/                 # podman-compose: postgres-age (pgcrypto+vchord_bm25) + web
├── data/                   # 默认数据根 (LAWRAG_DATA_ROOT 可改)
│   ├── law_index/                # 爬取的 NPC 索引 JSON
│   ├── downloaded_laws/*.docx     # 原始 docx
│   ├── raw_laws/*.txt            # markitdown 转出的纯文本
│   └── structured_laws/*.json     # parse_multi_level 输出的层级结构
├── static/                 # `just build-ui` 把 frontend/dist 拷贝到这里, 由 FastAPI /webui/* 挂载
├── .proj_root              # 环境变量自动向上查找的仓库根标记
├── .env                    # POSTGRES_* / LLM_* / USE_SELFHOSTED_LLM / DEEPSEEK_API_KEY 等环境变量
├── justfile                # 顶层一键命令 (web / initdb / setup / eval / ...)
└── 法律Agent需求.md         # 课程实习原始需求
```

详细目录与模块说明见:
- [backend/AGENTS.md](backend/AGENTS.md)
- [frontend/AGENTS.md](frontend/AGENTS.md)

## 🧰 技术栈

| 模块 | 选型 |
| --- | --- |
| 本地 LLM | 自托管 vLLM (`chat/chat_model.py`: `VLLMChatModel` + `VLLMProvider`, 默认 `qwen3.5`)，通过 `USE_SELFHOSTED_LLM=True` 启用；未启用时回退 `deepseek-v4-flash via DeepSeekProvider` |
| 文档爬取 | Python `scrapy` (`AsyncCrawlerRunner`) + 可选 `selenium` |
| 文本切分 | `spaCy` + `zh_core_web_trf` 句切分 + token overlap |
| 嵌入/重排 | `qwen3-embedding` (4096 维) + `qwen3-reranker`，统一通过 `LLM_LINK`（`chat` 与 `embedder` 复用同一端点） |
| 检索 | PostgreSQL 18 + `pgvector` (vector/halfvec/sparsevec) + `vchord` / `vchord_bm25` (BM25) |
| Agent 框架 | pydantic-ai (Agent + Capability + Subagent) |
| 系统界面 | FastAPI 0.119 (uvicorn 5 workers) + Vite 8 / React 19 / antd 6 / Emotion |

> 默认部署把 chat 与 embedding/rerank 集中到同一个 OpenAI 兼容 vLLM 端点（即同一个 `LLM_LINK`），由 `.env` 中的 `LLM_PROTOCOL/LLM_HOST/LLM_PORT` 拼出 `LLM_LINK = <scheme>://<host>:<port>/v1`。例：示例仓库 `https://nw.lonwell.cn:10001/v1`。
> 仅靠 BM25 (`USE_SELFHOSTED_LLM=False` 且无 `DEEPSEEK_API_KEY`) 也可启动但 Agent 不可用，仅混合检索 CLI (`just search`) 与 `/api/rag/*` REST 可用。

## 🚀 快速开始

### 前置条件

- Python **3.14 (< 3.15)**, 推荐 [uv](https://docs.astral.sh/uv/) 管理依赖
- Node ≥ 24 [pnpm](https://pnpm.io/) 管理前端依赖
- 可达的 PostgreSQL 18 (带 `pgcrypto` / `vchord` / `vchord_bm25` 扩展)
- 可达的 OpenAI 兼容 vLLM 端点：`USE_SELFHOSTED_LLM=true` 时需 `.env` 中 `LLM_*` (chat / embedding / rerank 都要走它)；若不自托管，可保留 `DEEPSEEK_API_KEY` 作为回退 (留空则 Agent 不可用, 仅 BM25 检索可用)

### 1. 配置环境变量

拷贝并按需修改:

```bash
cp .env.example .env   # 若无 example 可手抄 .env 字段
```

至少需要:

```dotenv
# FastAPI
FASTAPI_HOST=127.0.0.1
FASTAPI_PORT=40001

# PostgreSQL (默认本地 docker 端口 10004 / podman 端口 40002)
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=10004
POSTGRES_USER=postgres
POSTGRES_DB=data
POSTGRES_PASSWORD=postgresgraph

# 自托管 vLLM 端点（chat / embedding / rerank 共用）
LLM_PROTOCOL=https
LLM_HOST=nw.lonwell.cn
LLM_PORT=10001
USE_SELFHOSTED_LLM=true        # 设为 true 启用自托管 qwen3.5; 设 false 则回退到 DEEPSEEK_API_KEY

# 回退 provider（仅 USE_SELFHOSTED_LLM=false 时使用）
# DEEPSEEK_API_KEY=sk-...

# 数据根 (可选, 默认 <repo>/data)
# LAWRAG_DATA_ROOT=/path/to/data
```

### 2. 启动数据库与依赖

任选其一:

```bash
# 方式 A: 本机已装 PostgreSQL 18 + 扩展 (默认连 127.0.0.1:10004)
just initdb      # 装扩展 + 创建默认账号 admin/admin

# 方式 B: podman-compose 拉容器 (主机端口 40002 -> 容器 5432)
#         需把 .env 中的 POSTGRES_PORT 改为 40002
just database    # 仅数据库
just docker      # database + web 一起起
```

### 3. 抓取 → 解析 → 入库 → 嵌入

```bash
just spider-crawl         # NPC 数据库索引 (默认 all, 不含 dfxfg 地方性法规)
just spider-download      # 下载 docx 并转 structured_laws/*.json
just pageindex-import     # structured_laws/*.json 写入 law_nodes
just pageindex-embed      # 把法条分块并嵌入到 documents 表 (最耗时)
```

或一行:

```bash
just setup
```

### 4. 启动服务

```bash
# 后端 (终端 1)
just web              # http://127.0.0.1:40001

# 前端开发服务器 (终端 2, 带 /api 代理)
just ui               # http://127.0.0.1:5173/webui/

# 或者一次性构建前端并由后端托管
just build-ui         # 输出到 ./static/, 后端 /webui/* 自动挂载
```

打开 <http://127.0.0.1:40001/webui/>, 默认管理员账号 `admin/admin`。

### 5. 跑评估 (课程要求 ≥ 100 条问答)

```bash
just eval             # 全量 100 条, 报告写到 <DATA_ROOT>/eval/report.json
just eval 20          # 仅跑前 20 条
```

报告 JSON 与课程需求模板一致, 字段对应:

| 需求字段 | 报告字段 |
| --- | --- |
| `question` | `question` |
| `expected_answer` | `expected_answer` |
| `model_output` | `model_output` |
| `evaluation_note` | `evaluation_note` |
| (额外) | `success` (`LLMJudge` 通过标记), `error_message` (若失败) |

## 🛠️ 顶层命令一览 (justfile)

| 命令 | 作用 |
| --- | --- |
| `just setup` | initdb → spider-crawl → spider-download → pageindex-import → pageindex-embed → build-ui |
| `just web` | 启动 FastAPI (uvicorn 5 workers) |
| `just initdb` / `db-reset` / `db-clean` | 数据库初始化/重置/清空 |
| `just spider-crawl CATEGORY=all` | 抓取 NPC 法规索引 |
| `just spider-download` | 下载 + 解析 docx |
| `just pageindex-convert [FILTER]` | raw → structured (无需重新下载) |
| `just pageindex-import` | structured → law_nodes |
| `just pageindex-embed [LAW]` | law_nodes → documents |
| `just search QUERY [LIMIT=5]` | 走混合检索 CLI |
| `just eval [LIMIT]` | 跑内置 100 条法律问答评测 |
| `just ui` | 前端开发 |
| `just build-ui` | 前端 build + 拷贝到 `static/` |
| `just backend-format\|lint\|typecheck` | Python 格式化/lint/类型检查 |
| `just frontend-check\|typecheck` | 前端格式化+lint/biome/类型检查 |
| `just docker` / `just database` / `just docker-down` | 容器编排 |
| `just web-docker` | 仅起 web 容器 |

## 🧱 架构示意

```
                   ┌──────────────────────┐
                   │   React 19 (Vite 8)   │        /webui/* (静态)
                   │   + antd 6 + Emotion  │ ◄────────────────────┐
                   └──────────┬───────────┘                      │
                              │ /api proxy                      │
                              ▼                                 │
   ┌──────────────────────────────────────────────────────────┐  │
   │  FastAPI (uvicorn x5 + uvloop)                          │  │
   │  ┌────────────┐  ┌────────────┐  ┌──────────┐  ┌───────┐ │  │
   │  │ /api/users │  │ /api/chat  │  │ /api/rag │  │ /webui│ │  │
   │  └─────┬──────┘  └─────┬──────┘  └────┬─────┘  └───────┘ │  │
   │        │               │              │                   │  │
   │   UserManager    HistoryStore     RAGMode                │  │
   │   (JWT+pg crypt) (pydantic-ai    (RRF + rerank          │  │
   │                     ModelMessage)   + page index)        │  │
   │        │               │              │                   │  │
   │        └───────────────┼──────────────┘                   │  │
   │                        ▼                                  │  │
   │              ┌──────────────────────┐                    │  │
   │              │   pydantic-ai Agent   │                    │  │
   │              │   + 4 Capability     │                    │  │
   │              │   (RAG/Code/Web/     │                    │  │
   │              │    Subagent)         │                    │  │
   │              └──────────┬───────────┘                    │  │
   │                         │                                │  │
   │                  ┌──────┴───────┐                        │  │
   │                  ▼              ▼                        │  │
   │           ┌──────────────┐  ┌──────────────────┐         │  │
   │           │  USE_SELF    │  │  qwen3-embedding │         │  │
   │           │   HOSTED=true│  │  + qwen3-reranker│         │  │
   │           │  VLLMChat    │  │  (embedder.py)   │         │  │
   │           │  (qwen3.5)   │  │                  │         │  │
   │           └──────┬───────┘  └────────┬─────────┘         │  │
   │                  │                   │                   │  │
   │                  └────────┬──────────┘                   │  │
   │                           ▼                              │  │
   │                  ┌────────────────────┐                  │  │
   │                  │   LLM_LINK (/v1)   │ 自托管 vLLM 同一端点 │
   │                  └────────────────────┘                  │  │
   └──────────────────────────────────────────────────────────┘  │
                              │                                   │
                              ▼                                   │
              ┌──────────────────────────────┐                   │
              │   PostgreSQL 18               │                   │
              │   + pgcrypto + vchord        │                   │
              │   + vchord_bm25              │◄──────────────────┘
              │                              │   static/ 挂载点
              │  ┌─────────┐  ┌─────────┐    │
              │  │ users   │  │ sessions│    │
              │  ├─────────┤  │ histories│   │
              │  │ law_nodes (树)            │
              │  ├─────────┤                 │
              │  │ documents (vector+bm25)   │
              │  └─────────┘                 │
              └──────────────────────────────┘
```

## 🧪 测试

```bash
cd backend

uv run pytest                    # 全部
uv run pytest -m "not db"        # 跳过依赖真实数据库的测试
uv run pytest -m "db"            # 仅跑需要 db 的测试
uv run pytest tests/test_lawparser.py -k parse_multi_level -v
```

测试样例位于 `backend/tests/`:

- `test_lawparser.py` —— 离线：中文数字解析、层级结构扁平化、TOC 构建等
- `test_pageindex.py` —— 在线（`@pytest.mark.db`）：导入、列出、按条号取、按 path 取、TOC、删除

## 📦 数据落盘约定

默认数据根为 `<repo>/data/`, 通过 `LAWRAG_DATA_ROOT` 覆盖:

```
data/
├── law_index/law_index.json                # spider crawl 产物
├── downloaded_laws/<uuid>.docx            # spider download 原始文件
├── raw_laws/<law_name>.txt                 # markitdown 转换结果
├── structured_laws/<law_name>.json         # parse_multi_level 序列化结果 (pageindex import 输入)
└── eval/report.json                        # 每次 `just eval` 输出
```

## 🔐 配置参考

见 [backend/AGENTS.md#配置](backend/AGENTS.md)。`EnvironmentSettings` (`backend/lawrag/environments.py`) 自动沿父目录向上查找 `.proj_root` 标记并加载 `<repo>/.env`; 未找到则退到 `backend/.venv`。

## 🤝 二次开发提示

- 切换 LLM：在 `backend/lawrag/chat/model.py` 第 20-26 行通过 `USE_SELFHOSTED_LLM` 切换自托管 / DeepSeek；若要替换自托管模型，改 `backend/lawrag/chat/chat_model.py` 的 `CHAT_MODEL = "qwen3.5"`；
- 修改统一 LLM 端点：改 `.env` 中的 `LLM_PROTOCOL/LLM_HOST/LLM_PORT`（`LLM_LINK` 自动派生），`chat/chat_model.py` 与 `documents/embedder.py` 都从同一 `settings.LLM_LINK` 读取；
- 加新工具：在 `backend/lawrag/chat/<name>_tools.py` 定义 `@xxx_capability.tool`, 在 `backend/lawrag/chat/struct.py` 注册 `TOOL_REGISTRY`;
- 改切分粒度：调整 `backend/lawrag/documents/splitter.py` 的 `chunk_size` / `chunk_overlap`;
- 加前端页：在 `frontend/src/pages/` 加组件, 在 `frontend/src/main.tsx` 注册路由即可;
- 评估新题型：在 `backend/lawrag/eval/dataset.py` 的 `cases` 列表追加 `Case(...)`。

## 📝 课程产出对应表

| 需求条目 | 本仓库位置 |
| --- | --- |
| 学习并部署本地 LLM | `backend/lawrag/chat/chat_model.py` (`VLLMChatModel`/`VLLMProvider`) + `.env` 中 `USE_SELFHOSTED_LLM` / `LLM_*` |
| 编写爬虫, 爬取法律法规 | `backend/lawrag/spider/` (law_spider / content_spider / runner) |
| 文档清洗、分段, 向量化 | `backend/lawrag/documents/` (splitter / embedder / tokenizer) |
| 构建 RAG 问答系统 | `backend/lawrag/database/ragmode.py` (向量+BM25 RRF+rerrank) |
| 引入 Agentic Framework | `backend/lawrag/chat/` (pydantic-ai Agent + 4 Capability + 2 Subagent) |
| FastAPI 演示界面 | `backend/lawrag/routers/` + `frontend/` (由 FastAPI `/webui/*` 挂载) |
| 项目技术文档 | 本 README + `backend/AGENTS.md` + `frontend/AGENTS.md` |
| **≥ 100 条测试样本** | `backend/lawrag/eval/dataset.py` 内置 100 条, 用 `just eval` 跑评估并写报告 |
| GitHub 项目代码 + 文档 | 即本仓库 |
| 演示 PPT / 短视频 | optional, 由各组自行准备 |

## License

仅用于课程实习; 数据来源于 [NPC 法律法规数据库](https://flk.npc.gov.cn/), 请遵守其使用条款。

# ─── Backend ──────────────────────────────────────────────────────────────────

# 初始化数据库：装扩展 + 创建默认账号 admin/admin
initdb:
  cd backend && uv run lawrag database init

# 重置 / 清空数据库
db-reset DB="data":
  cd backend && uv run lawrag database reset -d {{DB}}
db-clean DB="data":
  cd backend && uv run lawrag database clean -d {{DB}}

# 启动 FastAPI（uvicorn 5 workers，加载 .env）
web:
  cd backend && uv run lawrag start

# 混合检索 CLI（不带 -k 时默认 5 条）
search QUERY LIMIT="5":
  cd backend && uv run lawrag search {{QUERY}} -k {{LIMIT}}

# 抓取 NPC 法律法规索引（默认 all，不含 dfxfg 地方性法规）
spider-crawl CATEGORY="all":
  cd backend && uv run lawrag spider crawl -c {{CATEGORY}}

# 下载+解析已抓取的索引
spider-download:
  cd backend && uv run lawrag spider download

# raw_laws/*.txt → structured_laws/*.json（无需重新下载）
pageindex-convert FILTER="":
  cd backend && uv run lawrag pageindex convert -f {{FILTER}}

# structured_laws/*.json → law_nodes
pageindex-import:
  cd backend && uv run lawrag pageindex import

# law_nodes → documents（向量+BM25 双索引，最耗时）
pageindex-embed LAW="" SIZE="4096" OVERLAP="128" BATCH="64":
  cd backend && uv run lawrag pageindex embed {{LAW}} -s {{SIZE}} -o {{OVERLAP}} -b {{BATCH}}

# 评测内置 100 条法律问答（写入 <DATA_ROOT>/eval/report.json）
eval LIMIT="":
  cd backend && uv run lawrag eval run -n {{LIMIT}}

# ─── Frontend ─────────────────────────────────────────────────────────────────

ui:
  cd frontend && pnpm dev

# 构建并拷贝到仓库根 static/，由 FastAPI 在 /webui/* 挂载
build-ui:
  cd frontend && pnpm build
  rm -rf static
  cp -r frontend/dist static

# ─── Quality ──────────────────────────────────────────────────────────────────

backend-format:
  cd backend && uv run ruff format
backend-lint:
  cd backend && uv run ruff check --fix
backend-typecheck:
  cd backend && uv run ty check --fix

frontend-check:
  cd frontend && pnpm check --write
frontend-typecheck:
  cd frontend && pnpm type-check

# ─── Docker (podman-compose) ──────────────────────────────────────────────────

database:
  cd docker && podman-compose up database

web-docker:
  cd docker && podman-compose up web

docker:
  cd docker && podman-compose up

docker-down:
  cd docker && podman-compose down

# ─── Convenience ──────────────────────────────────────────────────────────────

# 首次跑：initdb → spider-crawl → spider-download → pageindex-import → pageindex-embed → build-ui → web
setup: initdb spider-crawl spider-download pageindex-import pageindex-embed build-ui
  @echo "完成。运行 'just web' 启动服务，'just ui' 启动前端开发服务器。"

# ─── LLMServer ──────────────────────────────────────────────────────────────

llmserver:
  cd llmserver && uv run llmserver
# llmserver

Python 3.14 + vLLM 多模型推理服务，向 `backend/` 暴露 OpenAI 兼容 `/v1` 接口，同进程串行加载 chat / embedding / rerank 三类模型。

## 技术栈

- **运行时**: Python `>= 3.14, < 3.15`（lock 锁在 3.14）
- **GPU**: NVIDIA CUDA 13（`torch==2.11.0+cu130`、`vllm==0.25.1`、`flashinfer==0.6.13`）
- **Web 框架**: FastAPI + uvicorn（5 workers，uvloop，`uvicorn[standard]`）
- **推理**: `vllm[runai,fastsafetensors,tensorizer]`
- **辅助**: `markitdown[all]`、`asyncer`（`runnify` 把同步 typer 命令转异步）、`cupy-cuda13x`、`nixl[cu13]`
- **CLI**: typer（`llmserver start`）
- **包管理**: uv（中国科大 PyPI + NJU PyTorch + flashinfer 镜像）

## 项目结构

```
llmserver/
├── llmserver/
│   ├── __init__.py
│   ├── __main__.py            # CLI 入口 (typer) — 仅 start 一个子命令
│   ├── environments.py        # pydantic-settings，自动向上查找 .proj_root 并加载仓库根 .env
│   ├── routers/
│   │   └── api.py             # FastAPI app + /v1/chat/completions|embed|rerank|...
│   └── server/
│       ├── model_manager.py   # ModelManager: 读 model_launch.json → AsyncEngineArgs → AsyncLLM → HandleType
│       ├── media_processer.py # document/audio/image preprocesser（markitdown + LRU 缓存）
│       └── templete.py        # 各类 reranker 的 chat template（qwen3-reranker 等）
├── model_launch.json          # 模型启动配置（与后端模型 ID 对齐）
├── pyproject.toml             # 依赖 + ruff + ty + pytest 配置
└── uv.lock
```

> `find_project_directory()` 与后端 `environments.py` 行为一致：沿父目录向上找 `.proj_root`，找到后 `os.chdir`，随后从仓库根 `.env` 读取 `LLM_HOST/LLM_PORT/MODEL_CONFIG_PATH` 等。

> 当前尚未在 `llmserver/tests/` 建目录，新增测试时建议先创建并避免在无 GPU 环境下触发 `AsyncLLM.from_engine_args`。

## 模型 ID 与 `model_launch.json` 对齐

`backend/lawrag/chat/model.py` 默认 `CHAT_UID = "qwen3.5"`，`EMBEDDING_UID = "qwen3-embedding"`、`RERANKER_UID = "qwen3-reranker"`。`model_launch.json` 中的 `model_uid` 必须一致：

| 用途 | `model_uid` | 模型仓库 | 模型类型 |
| --- | --- | --- | --- |
| Chat / Agent | `qwen3.5` | `Qwen/Qwen3.5-122B-A10B-GPTQ-Int4` | `LLM`（generate + tool_call） |
| 嵌入 | `qwen3-embedding` | `Qwen/Qwen3-VL-Embedding-8B` | `embedding`（pooling/embed） |
| 重排 | `qwen3-reranker` | `Qwen/Qwen3-VL-Reranker-8B` | `rerank`（pooling/classify） |

新增模型时只需在 `model_launch.json` 追加一条 spec：`enabled=false` 跳过；`model_type` 决定 `runner/convert` 映射（`LLM/embedding/rerank/classify/asr/ocr`），无需改 `model_manager.py`。

> `backend` 调用 `POST /v1/embed` 与 `POST /v1/rerank`（multimodal embedding/rerank），与 `model_manager.py` 中的自定义路由对齐。

## 开发命令

```bash
cd llmserver

uv sync                          # 安装依赖（首次需 CUDA 13 环境）
uv run llmserver start --help    # 查看启动参数

# 本机启动（默认监听 0.0.0.0:8000，可被 .env 覆盖）
uv run llmserver start \
    --config-path llmserver/model_launch.json \
    --host 0.0.0.0 \
    --port 10001
```

`__main__.start` 内部 `os.chdir(find_project_directory())`，因此配置路径请使用相对仓库根的 `llmserver/model_launch.json`。顶层便捷命令：`just llmserver`。

## 环境变量

`environments.py` 从仓库根 `.env` 读取：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MODEL_CONFIG_PATH` | `<repo>/model_config.yaml` | CLI 未传 `--config-path` 时的默认配置 |
| `LLM_HOST` / `LLM_PORT` | `0.0.0.0` / `8000` | FastAPI 监听地址，被 `--host/--port` 覆盖 |
| `RAG_DATA_ROOT` | `<repo>/data` | 与 `backend/` 共用的数据根 |
| `SSL_KEY_PATH` / `SSL_CERT_PATH` | – | 可选 HTTPS |

> `backend/` 用的是 `LLM_PROTOCOL/LLM_HOST/LLM_PORT/LLM_LINK/LLM_API_KEY`，`llmserver/` 用的是 `LLM_HOST/LLM_PORT`。两者在 `.env` 同时设置时需保持端口一致，`backend` 才能把请求打到本服务 `/v1` 端点。

## 启动后验证

```bash
curl http://127.0.0.1:10001/v1/health        # → {"status":"ok"}
curl http://127.0.0.1:10001/v1/models        # 列出已加载 model_uid
curl http://127.0.0.1:10001/v1/embed \
    -H 'content-type: application/json' \
    -d '{"model":"qwen3-embedding","input":"测试"}'
```

## API 一览（`routers/api.py`）

`/v1/*` OpenAI 兼容 + 自定义路由：

- `/v1/health` (GET/POST)、`/v1/models`
- `/v1/chat/completions`、`/v1/completions`、`/v1/responses`
- `/v1/messages`（Anthropic Messages）
- `/v1/embed`（自定义，multimodal embedding，backend 使用）、`/v1/pooling`、`/v1/classify`、`/v1/score`、`/v1/rerank`
- `/v1/tokenize`、`/v1/detokenize`、`/v1/generate`
- `/v1/audio/transcriptions`、`/v1/audio/translations`
- `/v1/image/ocr`

`/v1/chat/completions` 在模型 spec 打开 `enable_auto_tool_choice` + `tool_call_parser` 后，即可被 `backend` 的 pydantic-ai Agent 作为工具调用后端使用。

## 代码规范

- 行宽 120，缩进 4 空格，LF，双引号。
- Lint / 格式化：`uv run ruff format` 与 `uv run ruff check --fix`。
- 类型检查：`uv run ty check --fix`（Python LSP 使用 ty + ruff）。
- 启用的 ruff 规则集：`F/E/W/I/N/FAST/PL/UP/NPY/PD/ASYNC/B/C4/FURB/PTH`（preview），忽略 `PLR0904/0911/0912/0913/0914/0915/0916/0917/1702/6301`、`PLC0415`、`PLW0603/1641/2901/3201`、`PLC1901`、`N801`、`PLR2004`。
- Python 3.14 语法：无需 `from __future__ import annotations`，`except` 多个异常可直接用逗号。

## 测试

```bash
cd llmserver
uv run pytest                 # 全部测试（需先创建 tests/ 目录）
```

> 模型加载类用例默认不在线；新增测试时请避免在无 GPU 的 CI 里触发 `AsyncLLM.from_engine_args`。

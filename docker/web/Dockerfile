FROM node:26-trixie as build-webui

COPY ./frontend /app/webui

WORKDIR /app/webui

ENV NPM_CONFIG_REGISTRY=https://registry.npmmirror.com \
    CI=true

RUN --mount=type=cache,target=/root/.cache/pnpm \
    --mount=type=cache,target=/root/.cache/node \
    --mount=type=cache,target=/root/.npm \
    corepack enable && \
    pnpm install --no-frozen-lockfile

RUN pnpm build

FROM python:3.14-trixie as builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 设置环境变量
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_NO_EDITABLE=1 \
    UV_FROZEN=1

# 安装系统依赖


# 设置工作目录
WORKDIR /app

# 使用 uv 安装依赖，利用 BuildKit 缓存挂载
# uv 的缓存目录默认在 /root/.cache/uv
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=./backend/pyproject.toml,target=/app/pyproject.toml \
    --mount=type=bind,source=./backend/uv.lock,target=/app/uv.lock \
    uv sync --no-install-project
# 复制应用代码
COPY ./backend/ ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync

FROM python:3.14-trixie as final

WORKDIR /app

COPY ./docker/debian.sources /etc/apt/sources.list.d/debian.sources

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y  curl locales && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    echo "zh_CN.UTF-8 UTF-8" >> /etc/locale.gen && \
    locale-gen && \
    touch /app/.proj_root && \
    rm -rf /tmp/*



# 复制构建产物
#COPY --from=build-webui /app/webui/dist ./static
COPY --from=builder /app/.venv /app/.venv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/



# 设置环境变量
ENV FASTAPI_HOST=0.0.0.0 \
    FASTAPI_PORT=8080 \
    POSTGRES_HOST=postgresql \
    POSTGRES_PORT=5432 \
    POSTGRES_USER=postgres \
    POSTGRES_PASSWORD=postgres

# 声明持久化数据卷
VOLUME ["/data"]

# 暴露端口
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD curl -X POST http://localhost:8080/api/health || exit 1

ENTRYPOINT [ "uv", "run", "lawrag"]
CMD ["start"]

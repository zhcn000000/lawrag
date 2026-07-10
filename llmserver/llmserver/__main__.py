import logging
from pathlib import Path
from typing import Annotated

import uvloop
import vllm
from asyncer import runnify
from rich import traceback
from rich.logging import RichHandler
from typer import Option, Typer
from uvicorn import Config, Server

from llmserver.environments import settings
from llmserver.routers.api import app, model_manager

cli = Typer(help="模型命令行接口.", pretty_exceptions_enable=False)  # 使用rich手动美化异常
logger = logging.getLogger(__name__)


@cli.command(help="启动模型服务端.")
@runnify
async def start(
    config_path: Annotated[Path | None, Option(help="模型启动配置文件路径")] = None,
    host: Annotated[str | None, Option(help="服务器监听地址，优先于环境变量 VLLM_HOST")] = None,
    port: Annotated[int | None, Option(help="服务器端口，优先于环境变量 VLLM_PORT")] = None,
) -> None:
    """启动服务，并在后台运行模型服务端线程."""
    actual_host = host if host is not None else settings.LLM_HOST
    actual_port = port if port is not None else settings.LLM_PORT

    logger.info(f"[llmserver] vLLM 版本: {vllm.__version__}")

    # 第三步：使用提供的配置路径或默认配置路径
    if config_path is None:
        config_path = settings.MODEL_CONFIG_PATH

    # 加载模型配置
    logger.info("[llmserver] 加载模型配置: %s", config_path)
    await model_manager.load_models_from_config(config_path)

    # 第四步：启动 FastAPI 服务器
    logger.info("[llmserver] 启动服务器: %s:%s", actual_host, actual_port)
    config = Config(
        app=app,
        host=actual_host,
        port=actual_port,
        log_level="info",
        workers=5,
        log_config=None,
        access_log=True,
        ssl_keyfile=settings.SSL_KEY_PATH,
        ssl_certfile=settings.SSL_CERT_PATH,
    )
    server = Server(config)
    await server.serve()


def main() -> None:
    traceback.install(show_locals=True)
    uvloop.install()
    logging.basicConfig(
        level=logging.INFO,
        handlers=[
            RichHandler(
                rich_tracebacks=True,
            ),
        ],
    )
    cli()


if __name__ == "__main__":
    main()

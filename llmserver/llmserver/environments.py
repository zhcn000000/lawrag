"""环境配置."""

import os
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def find_project_directory() -> Path:
    current_dir = Path(__file__).parent
    while True:
        if (Path(current_dir) / ".proj_root").exists():
            return Path(current_dir)
        parent_dir = Path(current_dir).parent
        if parent_dir == current_dir:
            break
        current_dir = parent_dir
    msg = ".proj_root not found in any parent directory."
    raise FileNotFoundError(msg)


os.chdir(find_project_directory())
env_file = find_project_directory() / ".env"
if not env_file.exists():
    env_file = None


class EnvironmentSettings(BaseSettings):
    """环境设置."""

    # 模型配置文件路径
    MODEL_CONFIG_PATH: Path = find_project_directory() / "llmserver" / "model_config.yaml"

    # 服务器配置
    LLM_HOST: str = "127.0.0.1"
    LLM_PORT: int = 8000
    DATA_ROOT: Annotated[Path, Field(alias="LAWRAG_DATA_ROOT")] = find_project_directory() / "data"
    SSL_KEY_PATH: Path | None = None
    SSL_CERT_PATH: Path | None = None
    model_config = SettingsConfigDict(env_ignore_empty=True, env_file=env_file, extra="ignore")


settings = EnvironmentSettings()


if env_file is not None:
    load_dotenv(dotenv_path=env_file)

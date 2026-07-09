import os
from pathlib import Path
from tempfile import mkdtemp
from typing import Annotated, Literal
from uuid import UUID

from dotenv import load_dotenv
from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

os.environ.setdefault("USER_AGENT", "Chrome/139.0.2171.99 Safari/537.36")


def find_project_directory() -> Path:
    current_dir = Path(__file__).parent
    while True:
        if (Path(current_dir) / ".proj_root").exists():
            return Path(current_dir)
        parent_dir = Path(current_dir).parent
        if parent_dir == current_dir:
            break
        current_dir = parent_dir
    current_dir = Path(__file__).parent.parent
    return current_dir


env_file = find_project_directory() / ".env"
if not env_file.exists():
    env_file = None


class EnvironmentSettings(BaseSettings):
    FASTAPI_HOST: str = "127.0.0.1"
    FASTAPI_PORT: int = 40001
    POSTGRES_HOST: str = "127.0.0.1"
    POSTGRES_PORT: int = 10004
    POSTGRES_USER: str = "postgres"
    POSTGRES_DB: str = "data"
    POSTGRES_DSN: PostgresDsn | None = None
    POSTGRES_PASSWORD: SecretStr = SecretStr("postgres_password")
    DATA_ROOT: Annotated[Path, Field(alias="LAWRAG_DATA_ROOT")] = find_project_directory() / "data"
    UUID_SEED: Annotated[UUID, Field(alias="LAWRAG_UUID_SEED")] = UUID("11fa063e-b366-41a9-ac97-439b0a561846")
    RELEASE_MODE: Annotated[bool, Field(alias="RAG_RELEASE_MODE")] = True
    TMP_DIR: Annotated[Path, Field(alias="RAG_TMP_DIR")] = Path(mkdtemp())
    TOKEN_EXPIRES_IN: Annotated[int, Field(alias="RAG_TOKEN_EXPIRES_IN")] = 3600 * 6
    JWT_SECRET: SecretStr = SecretStr("knowgraph-jwt-secret-change-in-production")
    SSL_KEY_PATH: Path | None = None
    SSL_CERT_PATH: Path | None = None
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    model_config = SettingsConfigDict(env_ignore_empty=True, env_file=env_file, extra="ignore")

    def model_post_init(self, context):
        if not self.RELEASE_MODE:
            import warnings

            warnings.warn(
                "Running in DEVELOPMENT mode",
                UserWarning,
                stacklevel=2,
            )
        if self.POSTGRES_DSN is None:
            self.POSTGRES_DSN = PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD.get_secret_value(),
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )


settings = EnvironmentSettings()

if env_file is not None:
    load_dotenv(dotenv_path=env_file)

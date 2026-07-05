from pydantic import BaseModel


class ModelDeps(BaseModel):
    max_result_retries: int = 3
    select_toolset: set[str] = {"rag_toolkit", "code_toolkit", "web_toolkit"}

from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import MultiModalContent


class Document(BaseModel):
    id: UUID | None = None
    content: str
    multimedia: list[MultiModalContent] | None = None
    name: str | None = None
    query_score: float | None = None
    embedding: list[float] | None = None
    token_count: dict[int, int] | None = None
    page_index: str | None = None
    node_path: str | None = None

from functools import cache
from uuid import UUID

import spacy
from pydantic import BaseModel


class Document(BaseModel):
    content: str
    image_url: str | None = None
    name: str | None = None
    query_score: float | None = None
    id: UUID | None = None
    page_index: str | None = None
    node_path: str | None = None


@cache
def get_nlp():
    return spacy.load("zh_core_web_trf")

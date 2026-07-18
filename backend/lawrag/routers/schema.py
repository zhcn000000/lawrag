from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from lawrag.chat.struct import SubagentInfo, ToolInfo


class StatusResponse(BaseModel):
    success: bool = True
    status: str = "Done"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCredentialsRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: UUID
    username: str


class UserListResponse(BaseModel):
    users: list[UserResponse]


class UpdateUserRequest(BaseModel):
    username: str | None = None
    password: str | None = None


class SearchRequest(BaseModel):
    query: str
    regex: str | None = None
    vecweight: float = 0.6
    k: int = 4


class SearchItem(BaseModel):
    content: str
    source_name: str | None = None
    page_index: str | None = None
    score: float | None = None


class SearchResponse(StatusResponse):
    results: list[SearchItem]


class DocumentUploadResponse(StatusResponse):
    doc_ids: list[str]


class ToolItem(BaseModel):
    name: str
    id: str
    args: dict[str, Any]


class FileItem(BaseModel):
    type: str
    name: str
    url: str


class SystemMessageItem(BaseModel):
    role: str
    content: str
    success: bool = True


class UserMessageItem(BaseModel):
    role: str
    content: str | None = None
    files: list[FileItem] | None = None
    success: bool = True


class ToolMessageItem(BaseModel):
    role: str
    tool_call_id: str
    name: str
    content: str | None = None
    files: list[FileItem] | None = None
    success: bool = True


class AssistantMessageItem(BaseModel):
    role: str
    content: str | None = None
    reasoning: str | None = None
    tool_calls: list[ToolItem] | None = None
    files: list[FileItem] | None = None
    success: bool = True


class ChatRequest(BaseModel):
    text: str
    files: Annotated[list[FileItem], Field(default_factory=list)]
    model: str | None = None
    thinking: bool = True
    tools: Annotated[
        frozenset[Literal["rag_toolkit", "code_toolkit", "web_toolkit", "subagent_toolkit"]],
        Field(default_factory=frozenset),
    ]


class ToolsListResponse(StatusResponse):
    tools: dict[str, ToolInfo]
    subagents: dict[str, SubagentInfo]


class ChatTitleRequest(BaseModel):
    text: str


class RenameRequest(BaseModel):
    name: str


class ChatTitleResponse(StatusResponse):
    title: str


class SessionCreateResponse(StatusResponse):
    session_id: UUID
    name: str


class SessionItem(BaseModel):
    session_id: UUID
    name: str


class SessionListResponse(StatusResponse):
    sessions: list[SessionItem]


class HistoryResponse(StatusResponse):
    messages: list[SystemMessageItem | UserMessageItem | AssistantMessageItem | ToolMessageItem]


ChatMessage = SystemMessageItem | UserMessageItem | AssistantMessageItem | ToolMessageItem


class PageIndexImportRequest(BaseModel):
    path: str


class PageIndexImportResultItem(BaseModel):
    file: str
    status: str
    count: int = 0


class PageIndexImportResponse(StatusResponse):
    results: list[PageIndexImportResultItem]


class LawArticleResponse(BaseModel):
    id: str
    law_name: str
    article_number: int
    content: str
    chapter_number: int | None = None
    chapter_title: str | None = None
    section_number: int | None = None
    section_title: str | None = None


class LawArticleListResponse(StatusResponse):
    articles: list[LawArticleResponse]


class LawArticleDetailResponse(StatusResponse):
    article: LawArticleResponse | None = None


class LawInfoItem(BaseModel):
    law_name: str
    article_count: int


class TocEntryItem(BaseModel):
    node_type: str
    number: int | None
    title: str | None
    path: str
    children: list[TocEntryItem] | None = None


class LawListResponse(StatusResponse):
    laws: list[LawInfoItem]


class LawTocResponse(StatusResponse):
    law_name: str
    toc: list[TocEntryItem]


# ── Knowledge Base Management ──


class KbLawOverviewItem(BaseModel):
    law_name: str
    law_type: str
    status: str
    publish_date: str | None = None
    has_raw: bool = False
    has_structured: bool = False
    in_nodes: bool = False
    article_count: int = 0
    chunk_count: int = 0


class KbOverviewResponse(StatusResponse):
    laws: list[KbLawOverviewItem]
    total: int = 0


class KbCrawlRequest(BaseModel):
    category: str = "all"


class KbDownloadRequest(BaseModel):
    law_ids: list[str] | None = None


class KbImportRequest(BaseModel):
    law_names: list[str]


class KbEmbedRequest(BaseModel):
    law_names: list[str]
    chunk_size: int = 4096
    chunk_overlap: int = 128
    batch_size: int = 64

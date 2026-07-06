from typing import Any
from uuid import UUID

from pydantic import BaseModel


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
    offset: int = 0
    k: int = 4


class SearchResponse(StatusResponse):
    results: list[dict[str, Any]]


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
    files: list[str | dict] = []
    model: str | None = None
    thinking: bool = True
    select_toolset: set[str] = {"rag_toolkit", "code_toolkit", "web_toolkit"}


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
    category: str | None = None


class PageIndexImportResponse(StatusResponse):
    results: list[dict[str, Any]]


class LawArticleResponse(BaseModel):
    id: str
    law_name: str
    article_number: int
    content: str


class LawArticleListResponse(StatusResponse):
    articles: list[LawArticleResponse]


class LawArticleDetailResponse(StatusResponse):
    article: LawArticleResponse | None = None


class LawListResponse(StatusResponse):
    laws: list[dict[str, Any]]

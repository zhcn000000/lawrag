from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import UUID

import orjson
from fastapi import APIRouter
from pydantic import TypeAdapter
from pydantic_ai import (
    AgentRun,
    AudioUrl,
    BinaryContent,
    DocumentUrl,
    FilePart,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ImageUrl,
    ModelRequest,
    ModelResponse,
    NativeToolCallPart,
    NativeToolReturnPart,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolReturnPart,
    UserContent,
    UserPromptPart,
    VideoUrl,
)
from pydantic_ai.direct import model_request
from starlette.responses import StreamingResponse

from lawrag.chat.model import agent, get_model_settings
from lawrag.chat.struct import SUBAGENT_REGISTRY, TOOL_REGISTRY, ModelDeps
from lawrag.database.history import HistoryStore

from .schema import (
    AssistantMessageItem,
    ChatMessage,
    ChatRequest,
    ChatTitleRequest,
    ChatTitleResponse,
    FileItem,
    HistoryResponse,
    RenameRequest,
    SessionCreateResponse,
    SessionItem,
    SessionListResponse,
    StatusResponse,
    SystemMessageItem,
    ToolItem,
    ToolMessageItem,
    ToolsListResponse,
    UserMessageItem,
)

router = APIRouter()

db = HistoryStore()


def _resolve_user_content(
    content: str | Sequence[UserContent] | Any | None,
) -> tuple[str | None, list[FileItem] | None]:
    from collections.abc import Iterable

    if content is None:
        return None, None
    if not isinstance(content, Iterable):
        content = [content]
    text = ""
    files = []
    for chunk in content:
        if isinstance(chunk, str):
            text += chunk
            continue
        if isinstance(chunk, VideoUrl):
            url = chunk.url
            name = chunk._identifier
            ty = "video"
        elif isinstance(chunk, AudioUrl):
            url = chunk.url
            name = chunk._identifier
            ty = "audio"
        elif isinstance(chunk, ImageUrl):
            url = chunk.url
            name = chunk._identifier
            ty = "image"
        elif isinstance(chunk, DocumentUrl):
            url = chunk.url
            name = chunk._identifier
            ty = "document"
        elif isinstance(chunk, BinaryContent):
            url = chunk.data_uri
            name = chunk._identifier
            ty = "binary"
            if chunk.is_audio:
                ty = "audio"
            elif chunk.is_video:
                ty = "video"
            elif chunk.is_image:
                ty = "image"
            elif chunk.is_document:
                ty = "document"
        else:
            if isinstance(chunk, Iterable):
                text += "\n\n" + orjson.dumps(chunk).decode("utf-8")
            else:
                text += str(chunk)
            continue
        files.append(FileItem(type=ty, name=name or "", url=url))
    return text.strip(), files or None


# ruff: noqa: ASYNC119
@router.post("/{session_id}/stream")
async def api_chat(
    session_id: UUID,
    request: ChatRequest,
) -> StreamingResponse:
    message_history = await db.aget_messages(session_id)
    deps = ModelDeps(select_toolset=request.tools)
    files: list[Any] = []
    messages: Sequence[UserContent] = [request.text] + files
    model_settings = get_model_settings(
        thinking=request.thinking,
    )

    async def event_stream_handler(
        agent_run: AgentRun[ModelDeps, str],
    ) -> AsyncIterator[ChatMessage]:
        async for node in agent_run:
            if agent.is_user_prompt_node(node):
                system_prompts = ""
                for msg in node.system_prompts:
                    if isinstance(msg, str):
                        system_prompts += msg + "\n"
                system_prompts = system_prompts.strip()
                if system_prompts:
                    yield SystemMessageItem(
                        role="system",
                        content=system_prompts,
                        success=True,
                    )
                content, files = _resolve_user_content(node.user_prompt)
                yield UserMessageItem(
                    role="user",
                    content=content or None,
                    files=files or None,
                    success=True,
                )
            elif agent.is_model_request_node(node) or agent.is_call_tools_node(node):
                async with node.stream(agent_run.ctx) as stream:  # type: ignore
                    async for event in stream:
                        if isinstance(event, PartStartEvent):
                            if isinstance(event.part, ThinkingPart):
                                yield AssistantMessageItem(
                                    role="assistant",
                                    reasoning=event.part.content,
                                )
                            elif isinstance(event.part, TextPart):
                                yield AssistantMessageItem(
                                    role="assistant",
                                    content=event.part.content,
                                )
                            elif isinstance(event.part, ToolCallPart | NativeToolCallPart):
                                pass
                            elif isinstance(event.part, FilePart):
                                yield AssistantMessageItem(
                                    role="assistant",
                                    files=[
                                        FileItem(
                                            type="binary",
                                            name=event.part.content._identifier or "",
                                            url=event.part.content.data_uri,
                                        ),
                                    ],
                                )
                        elif isinstance(event, PartDeltaEvent):
                            if isinstance(event.delta, ThinkingPartDelta):
                                yield AssistantMessageItem(
                                    role="assistant",
                                    reasoning=event.delta.content_delta,
                                )
                            elif isinstance(event.delta, TextPartDelta):
                                yield AssistantMessageItem(
                                    role="assistant",
                                    content=event.delta.content_delta,
                                )
                        elif isinstance(event, PartEndEvent):
                            if isinstance(event.part, ThinkingPart):
                                yield AssistantMessageItem(
                                    role="assistant",
                                    success=True,
                                )
                            elif isinstance(event.part, TextPart):
                                yield AssistantMessageItem(
                                    role="assistant",
                                    content=None,
                                    success=True,
                                )
                        elif isinstance(event, FunctionToolCallEvent):
                            yield AssistantMessageItem(
                                role="assistant",
                                tool_calls=[
                                    ToolItem(
                                        name=event.part.tool_name,
                                        id=event.part.tool_call_id,
                                        args=event.part.args_as_dict(),
                                    ),
                                ],
                                success=True,
                            )
                        elif isinstance(event, FunctionToolResultEvent):
                            if isinstance(event.part, ToolReturnPart | NativeToolReturnPart):
                                content, files = _resolve_user_content(event.part.content)
                                yield ToolMessageItem(
                                    role="tool",
                                    tool_call_id=event.part.tool_call_id,
                                    name=event.part.tool_name or "tool",
                                    content=content or None,
                                    files=files or None,
                                    success=True,
                                )
                            elif isinstance(event.part, RetryPromptPart):
                                content = event.part.content
                                if not isinstance(content, str):
                                    content = orjson.dumps(content).decode("utf-8")
                                yield ToolMessageItem(
                                    role="tool",
                                    tool_call_id=event.part.tool_call_id,
                                    name=event.part.tool_name or "tool",
                                    content=content,
                                    success=False,
                                )

    async def stream_generator() -> AsyncIterator[str]:
        async with agent.iter(
            user_prompt=messages,
            deps=deps,
            message_history=message_history,
            model_settings=model_settings,
        ) as agent_run:
            async for chunk in event_stream_handler(agent_run):
                yield f"data: {chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
            if agent_run.result:
                await db.aadd_messages(agent_run.result.new_messages(), session_id)

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
    )


@router.get("/{session_id}/history")
async def api_history(
    session_id: UUID,
) -> HistoryResponse:
    history_lists: list[ChatMessage] = []
    raw_history = await db.aget_messages(session_id)
    for item in raw_history:
        if isinstance(item, ModelRequest):
            for part in item.parts:
                if isinstance(part, SystemPromptPart):
                    if part.content.strip():
                        history_lists.append(SystemMessageItem(role="system", content=part.content, success=True))
                elif isinstance(part, UserPromptPart):
                    content, files = _resolve_user_content(part.content)
                    history_lists.append(
                        UserMessageItem(
                            role="user",
                            content=content or None,
                            files=files or None,
                            success=True,
                        ),
                    )
                elif isinstance(part, ToolReturnPart | NativeToolReturnPart):
                    content, files = _resolve_user_content(part.content)
                    history_lists.append(
                        ToolMessageItem(
                            role="tool",
                            tool_call_id=part.tool_call_id,
                            name=part.tool_name or "tool",
                            content=content or None,
                            files=files or None,
                            success=True,
                        ),
                    )
                elif isinstance(part, RetryPromptPart):
                    history_lists.append(
                        ToolMessageItem(
                            role="tool",
                            tool_call_id=part.tool_call_id,
                            name=part.tool_name or "tool",
                            content=part.content
                            if isinstance(part.content, str)
                            else orjson.dumps(part.content).decode("utf-8"),
                            success=False,
                        ),
                    )
        elif isinstance(item, ModelResponse):
            aimsg = AssistantMessageItem(role="assistant")
            for part in item.parts:
                if isinstance(part, ThinkingPart):
                    aimsg.reasoning = part.content
                elif isinstance(part, TextPart):
                    aimsg.content = part.content
                elif isinstance(part, ToolCallPart | NativeToolCallPart):
                    if aimsg.tool_calls is None:
                        aimsg.tool_calls = []
                    aimsg.tool_calls.append(
                        ToolItem(id=part.tool_call_id, name=part.tool_name, args=part.args_as_dict()),
                    )
                elif isinstance(part, FilePart):
                    if aimsg.files is None:
                        aimsg.files = []
                    aimsg.files.append(
                        FileItem(
                            type="binary",
                            name=part.content._identifier or "",
                            url=part.content.data_uri,
                        ),
                    )
            aimsg.success = True
            history_lists.append(aimsg)
    return HistoryResponse(success=True, status="获取历史记录成功", messages=history_lists)


@router.post("/title")
async def api_generate_session_title(
    request: ChatTitleRequest,
) -> ChatTitleResponse:
    model = agent.model
    assert model is not None, "Agent's model is not defined"
    response = await model_request(
        model=model,
        messages=[
            ModelRequest.user_text_prompt(
                user_prompt=request.text,
                instructions="请根据以上用户询问内容生成一个简洁的当前会话的标题，要求突出主题，"
                "10个字左右，最多不超过20字，不要输出与标题无关的内容，注意不是回答用户问题，而是生成会话标题方便用户寻找",
            ),
        ],
        model_settings=get_model_settings(
            thinking=False,
            max_tokens=20,
            temperature=0.0,
        ),
    )
    title = response.text
    if title is None:
        return ChatTitleResponse(success=False, status="生成标题失败", title="")
    return ChatTitleResponse(success=True, status="生成标题成功", title=title)


@router.post("/")
async def api_create_session(
    request: RenameRequest,
) -> SessionCreateResponse:
    session_id = await db.acreate_session(request.name)
    return SessionCreateResponse(success=True, status="会话创建成功", session_id=session_id, name=request.name)


@router.delete("/{session_id}")
async def api_delete_session(
    session_id: UUID,
) -> StatusResponse:
    await db.adelete_session(session_id)
    return StatusResponse(success=True, status="会话删除成功")


@router.patch("/{session_id}")
async def api_rename_session(
    session_id: UUID,
    request: RenameRequest,
) -> StatusResponse:
    await db.arename_session(session_id, request.name)
    return StatusResponse(success=True, status="会话重命名成功")


@router.get("/list")
async def api_session_list() -> SessionListResponse:
    sessions = await db.alist_sessions()
    sessions = TypeAdapter(list[SessionItem]).validate_python(sessions, extra="ignore")
    return SessionListResponse(success=True, status="获取会话列表成功", sessions=sessions)


@router.get("/tools")
async def api_list_tools() -> ToolsListResponse:
    return ToolsListResponse(success=True, status="获取工具列表成功", tools=TOOL_REGISTRY, subagents=SUBAGENT_REGISTRY)

import base64
import hashlib
import mimetypes
import re
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

import requests
from asyncer import asyncify
from fastapi import UploadFile
from markitdown import (
    DocumentConverterResult,
    MarkItDown,
    StreamInfo,
)
from vllm.entrypoints.chat_utils import ChatCompletionMessageParam
from vllm.entrypoints.speech_to_text.transcription.protocol import TranscriptionRequest

if TYPE_CHECKING:
    from .model_manager import ModelManager, OCRRequest, OCRResponse
# 直接缓存转换后的消息列表（包含图片音频和文本）
_CACHE: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
_CACHE_MAX_SIZE = 1000


def _get_url_hash(url: str) -> str:
    """生成 URL 的哈希值作为缓存键."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _get_from_cache(url: str) -> list[dict[str, Any]] | None:
    """从缓存中获取转换后的消息列表，如果存在则移到最前面（LRU）."""
    cache_key = _get_url_hash(url)
    if cache_key in _CACHE:
        # 移到末尾（最近使用）
        _CACHE.move_to_end(cache_key)
        return _CACHE[cache_key]
    return None


def _add_to_cache(url: str, result_parts: list[dict[str, Any]]) -> None:
    """添加转换后的消息列表到缓存，如果超过最大容量则删除最旧的."""
    cache_key = _get_url_hash(url)

    # 如果已存在，先删除旧的
    if cache_key in _CACHE:
        del _CACHE[cache_key]

    # 添加新的到末尾
    _CACHE[cache_key] = result_parts

    # 如果超过最大容量，删除最旧的（开头的）
    if len(_CACHE) > _CACHE_MAX_SIZE:
        _CACHE.popitem(last=False)


async def document_processer(
    messages: list[ChatCompletionMessageParam],
) -> list[ChatCompletionMessageParam]:
    """Process messages and convert document_url type to text and images.

    Converts: {"type":"document_url", "document_url": {"url":"http://example.com/doc.pdf"}}
    To: [
        {"type": "image_url", "image_url": {"url": "data:image/..."}},  # 如果有图片
        {"type": "text", "text": "<document>...content...</document>"}
    ]

    Features:
    - Caches converted message parts (images + text) using LRU strategy (max 1000 entries)
    - Fast cache lookup - directly returns cached results without re-parsing
    - Extracts images from documents and adds them as image_url parts
    - Supports HTTP/HTTPS URLs and data URIs
    """
    processed_messages: list[ChatCompletionMessageParam] = []

    for message in messages:
        # 转换为字典进行处理
        msg_dict = dict(message)
        content = msg_dict.get("content")

        if isinstance(content, str):
            processed_messages.append(message)
        elif isinstance(content, list):
            new_content = await _process_document_parts(content)
            msg_dict["content"] = new_content
            processed_messages.append(msg_dict)  # type: ignore
        else:
            # 其他情况保持不变
            processed_messages.append(message)

    return processed_messages


async def audio_processer(
    messages: list[ChatCompletionMessageParam],
    model_server: ModelManager,
    *,
    language: str | None = None,
    model: str | None = None,
) -> list[ChatCompletionMessageParam]:
    """Process messages and convert audio_url type to text via transcription.

    Converts: {"type":"audio_url", "audio_url": {"url":"http://example.com/audio.wav"}}
    To: [{"type": "text", "text": "<audio>...transcript...</audio>"}]

    Features:
    - Caches transcription text using LRU strategy (max 1000 entries)
    - Reuses shared stream extraction logic (HTTP/HTTPS/Data URI)
    """
    if model_server is None:
        return messages

    processed_messages: list[ChatCompletionMessageParam] = []

    for message in messages:
        msg_dict = dict(message)
        content = msg_dict.get("content")

        if isinstance(content, str):
            processed_messages.append(message)
        elif isinstance(content, list):
            new_content = await _process_audio_parts(
                content,
                model_server,
                language=language,
                model=model,
            )
            msg_dict["content"] = new_content
            processed_messages.append(msg_dict)  # type: ignore
        else:
            processed_messages.append(message)

    return processed_messages


async def image_processer(
    messages: list[ChatCompletionMessageParam],
    model_server: ModelManager,
    *,
    model: str | None = None,
) -> list[ChatCompletionMessageParam]:
    """Process messages and convert image_url type to text.

    Converts: {"type":"image_url", "image_url": {"url":"http://example.com/image.png"}}
    To: [{"type": "text", "text": "<image>...description...</image>"}]

    Features:
    - Caches converted text using LRU strategy (max 1000 entries)
    - Fast cache lookup - directly returns cached results without re-parsing
    - Supports HTTP/HTTPS URLs and data URIs
    """
    processed_messages: list[ChatCompletionMessageParam] = []

    for message in messages:
        msg_dict = dict(message)
        content = msg_dict.get("content")

        if isinstance(content, str):
            processed_messages.append(message)
        elif isinstance(content, list):
            new_content = await _process_image_parts(content, model_server, model=model)
            msg_dict["content"] = new_content
            processed_messages.append(msg_dict)  # type: ignore
        else:
            processed_messages.append(message)

    return processed_messages


async def _process_document_parts(content_parts: list[Any]) -> list[dict[str, Any]]:
    """Process content parts and convert document_url to text."""
    new_content = []

    for part in content_parts:
        if not isinstance(part, dict):
            new_content.append(part)
            continue

        part_type = part.get("type")

        if part_type == "document_url":
            # 转换文档URL，可能返回多个部分（文本 + 图片）
            converted_parts = await _convert_document_url_part(part)
            new_content.extend(converted_parts)
        else:
            # 其他类型(text, image_url等)保持不变
            new_content.append(part)

    return new_content


async def _process_audio_parts(
    content_parts: list[Any],
    model_server: ModelManager,
    *,
    language: str | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    new_content: list[dict[str, Any]] = []

    for part in content_parts:
        if not isinstance(part, dict):
            new_content.append(part)
            continue

        part_type = part.get("type")

        if part_type == "audio_url":
            converted_parts = await _convert_audio_url_part(
                part,
                model_server,
                language=language,
                model=model,
            )
            new_content.extend(converted_parts)
        elif part_type == "input_audio":
            converted_parts = await _convert_input_audio_part(
                part,
                model_server,
                language=language,
                model=model,
            )
            new_content.extend(converted_parts)
        else:
            new_content.append(part)

    return new_content


async def _process_image_parts(
    content_parts: list[Any],
    model_server: ModelManager,
    *,
    model: str | None = None,
) -> list[dict[str, Any]]:
    new_content: list[dict[str, Any]] = []

    for part in content_parts:
        if not isinstance(part, dict):
            new_content.append(part)
            continue

        part_type = part.get("type")

        if part_type == "image_url":
            converted_parts = await _convert_image_url_part(part, model_server, model=model)
            new_content.extend(converted_parts)
        else:
            new_content.append(part)

    return new_content


async def _convert_document_url_part(part: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a document_url part to text and image parts."""
    document_url_data = part.get("document_url", {})
    url = document_url_data.get("url")

    if not url:
        msg = "document_url part missing 'url' field"
        raise ValueError(msg)

    # 先尝试从缓存获取最终转换结果
    cached_result = _get_from_cache(url)
    if cached_result is not None:
        # 缓存命中，直接返回
        return cached_result

    # 缓存未命中，先提取文件流与元信息，再进行文档转换
    content_stream, stream_info = _extract_stream_from_url(url)
    document = await _convert_document_stream_to_markdown(content_stream, stream_info)

    markdown = document.text_content

    # 提取图片并构建结果

    # 提取所有 data: 开头的图片 URL
    image_urls = _extract_image_urls(markdown)

    # 如果有图片，先添加图片，再添加处理后的文本
    result_parts = [{"type": "image_url", "image_url": {"url": img_url}} for img_url in image_urls]

    # 添加文本部分（移除图片URL）
    cleaned_markdown = _remove_urls(markdown)
    result_parts.append({"type": "text", "text": "<document>\n" + cleaned_markdown + "\n</document>"})

    # 缓存最终结果
    _add_to_cache(url, result_parts)

    return result_parts


async def _convert_image_url_part(
    part: dict[str, Any],
    model_server: ModelManager,
    *,
    model: str | None = None,
) -> list[dict[str, Any]]:
    image_url_data = part.get("image_url", {})
    url = image_url_data.get("url")
    if not url:
        msg = "image_url part missing 'url' field"
        raise ValueError(msg)
    cached = _get_from_cache(url)
    if cached is not None:
        return cached
    content_stream, stream_info = _extract_stream_from_url(url)
    content_stream.seek(0)
    image_bytes = content_stream.read()
    request = OCRRequest(
        model=model or "deepseek-ocr-2",
        file=UploadFile(filename=stream_info.filename or "image", file=BytesIO(image_bytes)),
        stream=False,
    )
    response = await model_server.create_ocr(image_bytes, request)
    assert isinstance(response, OCRResponse)
    text = response.text if hasattr(response, "text") else ""
    result_part = [{"type": "text", "text": "<image>\n" + text + "\n</image>"}]
    _add_to_cache(url, result_part)
    return result_part


async def _convert_audio_url_part(
    part: dict[str, Any],
    model_server: ModelManager,
    *,
    model: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    audio_url_data = part.get("audio_url", {})
    url = audio_url_data.get("url")

    if not url:
        msg = "audio_url part missing 'url' field"
        raise ValueError(msg)

    cached = _get_from_cache(url)
    if cached is not None:
        return cached

    content_stream, stream_info = _extract_stream_from_url(url)
    content_stream.seek(0)
    audio_bytes = content_stream.read()

    filename = stream_info.filename
    if not filename:
        extension = stream_info.extension or ""
        filename = f"audio{extension}"

    upload = UploadFile(
        filename=filename,
        file=BytesIO(audio_bytes),
    )

    request = TranscriptionRequest(
        file=upload,
        model=model or "qwen3-asr",
        language=language,
        response_format="text",
        seed=None,
    )

    response = await model_server.create_transcription(
        audio_data=audio_bytes,
        request=request,
    )

    transcription_text = _extract_transcription_text(response)
    result_part = [{"type": "text", "text": f"<audio>\n{transcription_text}\n</audio>"}]
    _add_to_cache(url, result_part)

    return result_part


async def _convert_input_audio_part(
    part: dict[str, Any],
    transcription_server: ModelManager,
    *,
    model: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    input_audio_data = part.get("input_audio", {})
    if not isinstance(input_audio_data, dict):
        msg = "input_audio part missing 'input_audio' object"
        raise ValueError(msg)

    cache_key, content_stream, stream_info = _extract_stream_from_input_audio_data(input_audio_data)

    cached = _get_from_cache(cache_key)
    if cached is not None:
        return cached

    content_stream.seek(0)
    audio_bytes = content_stream.read()

    filename = stream_info.filename
    if not filename:
        extension = stream_info.extension or ""
        filename = f"audio{extension}"

    upload = UploadFile(
        filename=filename,
        file=BytesIO(audio_bytes),
    )

    request = TranscriptionRequest(
        file=upload,
        model=model or "qwen3-asr",
        language=language,
        response_format="text",
        seed=None,
    )

    response = await transcription_server.create_transcription(
        audio_data=audio_bytes,
        request=request,
    )

    transcription_text = _extract_transcription_text(response)
    result_part = [{"type": "text", "text": f"<audio>\n{transcription_text}\n</audio>"}]
    _add_to_cache(cache_key, result_part)

    return result_part


def _extract_transcription_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        return response.get("text", "")
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    return ""


def _extract_stream_from_input_audio_data(input_audio_data: dict[str, Any]) -> tuple[str, BytesIO, StreamInfo]:
    """从 OpenAI `input_audio` 结构中提取音频流、元信息和缓存键."""
    # 支持两种形式：
    # 1) {"url": "http(s)://..."} 或 data URI
    # 2) {"data": "<base64>", "format": "wav|mp3|..."}
    url = input_audio_data.get("url")
    if isinstance(url, str) and url:
        content_stream, stream_info = _extract_stream_from_url(url)
        return url, content_stream, stream_info

    data_b64 = input_audio_data.get("data")
    if not isinstance(data_b64, str) or not data_b64:
        msg = "input_audio part missing 'url' or base64 'data' field"
        raise ValueError(msg)

    audio_format = input_audio_data.get("format")
    extension = None
    if isinstance(audio_format, str) and audio_format:
        normalized = audio_format.strip().lower().lstrip(".")
        extension = f".{normalized}"

    audio_bytes = base64.b64decode(data_b64)
    data_hash = hashlib.sha256(audio_bytes).hexdigest()
    cache_key = f"input_audio:{data_hash}:{extension or ''}"

    stream_info = StreamInfo(
        extension=extension,
        filename=f"audio{extension or ''}",
    )
    return cache_key, BytesIO(audio_bytes), stream_info


def _extract_stream_from_url(url: str) -> tuple[BytesIO, StreamInfo]:
    """从 URL 提取文件内容流与元信息（可复用到 audio_url 等场景）."""
    if url.startswith(("http://", "https://")):
        return _extract_stream_from_http(url)
    if url.startswith("data:"):
        return _extract_stream_from_data_uri(url)
    msg = f"Invalid URL format: {url}"
    raise TypeError(msg)


async def _convert_document_stream_to_markdown(
    content_stream: BytesIO,
    stream_info: StreamInfo,
) -> DocumentConverterResult:
    """将文件流转换为 Markdown 文本（文档类型处理逻辑）."""
    md = MarkItDown()
    return await asyncify(md.convert_stream)(
        content_stream,
        stream_info=stream_info,
        keep_data_uris=True,
    )


def _extract_image_urls(markdown: str) -> list[str]:
    """从 Markdown 中提取所有 data: 格式的图片 URL."""
    # 匹配 Markdown 图片语法: ![alt](data:image/...)
    # 或者直接的 data:image/... URL
    pattern = r"!\[([^\]]*)\]\((data:image/[^)]+)\)|(?:^|\s)(data:image/[^\s\)]+)"
    matches = re.findall(pattern, markdown)

    image_urls = []
    for match in matches:
        # match 是一个元组，包含三个组
        # (alt_text, url_from_markdown_syntax, url_standalone)
        url = match[1] or match[2]

        # 验证URL包含逗号（base64编码标志），跳过不完整的URL
        if url and "," in url:
            image_urls.append(url)

    return image_urls


def _remove_urls(markdown: str) -> str:
    """从 Markdown 中移除 data: 格式的 URL，保留占位符."""
    # 图片
    markdown = re.sub(r"!\[([^\]]*)\]\(data:image/[^)]+\)", r"[图片: \1]", markdown)
    markdown = re.sub(r"(?:^|\s)(data:image/[^\s\)]+)", " [图片]", markdown)

    # 音频
    markdown = re.sub(r"!\[([^\]]*)\]\(data:audio/[^)]+\)", r"[音频: \1]", markdown)
    markdown = re.sub(r"(?:^|\s)(data:audio/[^\s\)]+)", " [音频]", markdown)

    # 视频
    markdown = re.sub(r"!\[([^\]]*)\]\(data:video/[^)]+\)", r"[视频: \1]", markdown)
    markdown = re.sub(r"(?:^|\s)(data:video/[^\s\)]+)", " [视频]", markdown)

    # 其他未知 data: URL
    markdown = re.sub(r"!\[([^\]]*)\]\(data:[^)]+\)", r"[未知: \1]", markdown)
    return re.sub(r"(?:^|\s)(data:[^\s\)]+)", " [未知]", markdown)


def _extract_stream_from_http(url: str) -> tuple[BytesIO, StreamInfo]:
    response = requests.get(url)
    mimetype = None
    charset = None
    if "content-type" in response.headers:
        parts = response.headers["content-type"].split(";")
        mimetype = parts[0].strip() if parts else None
        for part in parts[1:]:
            if part.strip().startswith("charset="):
                charset = part.split("=")[1].strip().strip("\"'")

    # 提取 filename 和 extension
    filename = None
    extension = None

    # 首先尝试从 Content-Disposition 头获取
    if "content-disposition" in response.headers:
        match = re.search(
            r'filename\*?=(["\']?)(?:UTF-8\'\')?(.+?)\1(?:;|$)',
            response.headers["content-disposition"],
        )
        if match:
            filename = match.group(2).strip("\"'")
            # URL decode if needed

            filename = unquote(filename)
            _, extension = Path(filename).suffix

    # 如果没有从头部获取到，尝试从 URL 路径提取
    if filename is None:
        parsed_url = urlparse(url)
        path = parsed_url.path
        if path and not path.endswith("/"):
            filename = Path(path).name
            # URL decode

            filename = unquote(filename)
            extension = Path(filename).suffix
    stream_info = StreamInfo(
        mimetype=mimetype,
        extension=extension or None,
        charset=charset,
        filename=filename,
        url=url,
    )

    content_stream = BytesIO(response.content)
    return content_stream, stream_info


def _extract_stream_from_data_uri(data_uri: str) -> tuple[BytesIO, StreamInfo]:
    # Data URI 格式: data:[<mimetype>][;charset=<charset>][;base64],<data>
    # 使用正则表达式一次性提取各部分
    data_uri_pattern = r"^data:([^;,]*)?(?:;charset=([^;,]+))?(?:;(base64))?,(.*)$"
    match = re.match(data_uri_pattern, data_uri)
    if not match:
        msg = "Invalid data URI format"
        raise ValueError(msg)

    mimetype = match.group(1) or None
    charset = match.group(2) or None
    is_base64 = match.group(3) == "base64"
    if not is_base64:
        msg = "Only base64-encoded data URIs are supported"
        raise ValueError(msg)
    data_part = match.group(4)
    data = base64.b64decode(data_part)
    extension = None
    if mimetype:
        # 根据 mimetype 推断扩展名

        guessed_ext = mimetypes.guess_extension(mimetype)
        if guessed_ext:
            extension = guessed_ext
    stream_info = StreamInfo(
        mimetype=mimetype,
        extension=extension,
        charset=charset,
    )
    content_stream = BytesIO(data)
    return content_stream, stream_info

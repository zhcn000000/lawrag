import ipaddress
import re
import socket
from functools import cache
from mimetypes import guess_type
from typing import Annotated, TypedDict
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from exa_py import AsyncExa
from exa_py.api import Category, SearchType
from httpx2 import AsyncClient, HTTPStatusError
from pydantic import Field
from pydantic_ai import BinaryContent, ModelRetry, RunContext, ToolDefinition
from pydantic_ai.capabilities import Capability

from .struct import ModelDeps

web_capability: Capability[ModelDeps] = Capability()


async def prepare_web(ctx: RunContext[ModelDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    if "web_toolkit" in ctx.deps.select_toolset:
        return tool_def
    return None


@web_capability.instructions
def web_instructions(ctx: RunContext[ModelDeps]) -> str | None:
    if "web_toolkit" not in ctx.deps.select_toolset:
        return None
    text = """当前已经启用了网络搜索功能，你可以使用search_web工具来进行网络搜索，或者使用fetch_web工具来获取网页内容。
在rag工具集也被开启的情况下，优先使用rag工具集来搜索法律法规、司法解释等内容，只有在rag工具集无法满足需求时，才使用网络搜索功能。"""
    return text


@cache
def _get_exa() -> AsyncExa:
    return AsyncExa()


class SearchResult(TypedDict):
    summary: str
    text: str


@web_capability.tool(
    name="search_web",
    description="网络搜索工具，输入搜索关键词，返回搜索结果摘要。可用于补充法律法规、司法解释等背景信息。",
    prepare=prepare_web,
    include_return_schema=True,
)
async def search_web(
    ctx: RunContext[ModelDeps],
    query: Annotated[str, Field(description="搜索关键词")],
    max_results: Annotated[int, Field(description="返回的最大搜索结果数量")] = 5,
    include_domains: Annotated[list[str] | None, Field(description="要包含的域名列表")] = None,
    exclude_domains: Annotated[list[str] | None, Field(description="要排除的域名列表")] = None,
    search_type: Annotated[SearchType | None, Field(description="搜索类型: auto/fast/deep等")] = None,
    category: Annotated[Category | None, Field(description="搜索类别: company, news, research paper等")] = None,
) -> list[SearchResult]:
    try:
        response = await _get_exa().search(
            query,
            num_results=max_results,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
            type=search_type,
            category=category,
        )
        results: list[SearchResult] = []
        for result in response.results:
            results.append(
                SearchResult(
                    summary=result.summary or "",
                    text=result.text or "",
                ),
            )
        return results

    except Exception as e:
        raise ModelRetry(f"网络搜索失败: {e!s}") from e


@web_capability.tool(
    name="fetch_web",
    description="获取网页原始内容工具，输入网页URL，返回网页的内容。",
    prepare=prepare_web,
    include_return_schema=True,
)
async def fetch_web(
    ctx: RunContext[ModelDeps],
    url: Annotated[str, Field(description="要获取内容的网页URL")],
    content_type: Annotated[
        str | None,
        Field(
            description="指定返回内容类型: text/html, application/json, text/plain, application/octet-stream等，"
            "未指定则从链接url后缀或返回body的Content-Type中推断",
        ),
    ] = None,
) -> str | BinaryContent:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ModelRetry("仅支持 http/https 协议的 URL")
        if parsed.hostname:
            try:
                ip = ipaddress.ip_address(socket.gethostbyname(parsed.hostname))
            except ValueError as e:
                raise ModelRetry(f"无效的 IP 地址: {e!s}") from e
            except socket.gaierror as e:
                raise ModelRetry(f"无法解析域名: {e!s}") from e
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                raise ModelRetry("不允许访问内网地址")

        async with AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()

            mime_main = (content_type or response.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()

            media_type = mime_main or guess_type(parsed.path or url)[0] or "application/octet-stream"

            if not media_type.startswith(("image/", "video/", "audio/")):
                try:
                    text = response.text
                except UnicodeDecodeError:
                    pass
                else:
                    if re.match(r"^data:[^,]+,[\s\S]*$", text):
                        return BinaryContent.from_data_uri(text)
                    if media_type == "text/html":
                        soup = BeautifulSoup(text, "html.parser")
                        text = soup.get_text(separator="\n", strip=True)
                        if response.url and response.url != url:
                            text = f"[重定向自: {url}]\n\n{text}"
                    return text

            return BinaryContent(
                data=response.content,
                media_type=media_type,
            )
    except HTTPStatusError as e:
        raise ModelRetry(f"HTTP {e.response.status_code} {e.response.reason_phrase or ''}: 请求 {url} 失败") from e
    except ModelRetry:
        raise
    except Exception as e:
        raise ModelRetry(f"获取网页内容失败: {e!s}") from e

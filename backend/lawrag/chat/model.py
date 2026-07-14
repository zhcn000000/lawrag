import logging
from collections.abc import Sequence

from httpx2 import AsyncClient, HTTPStatusError, NetworkError, TimeoutException
from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionUserMessageParam,
)
from pydantic_ai import (
    AudioUrl,
    BinaryContent,
    DocumentUrl,
    ImageUrl,
    ModelProfile,
    UserPromptPart,
    VideoUrl,
)
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers import Provider
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig
from tenacity import before_sleep_log, retry_if_exception, stop_after_attempt, wait_exponential

from lawrag.documents.models import Document
from lawrag.environments import settings

logger = logging.getLogger(__name__)

BASE_URL = str(settings.LLM_LINK).removesuffix("/")
API_KEY = settings.LLM_API_KEY
CHAT_UID = "qwen3.5"
EMBEDDING_UID = "qwen3-embedding"
RERANKER_UID = "qwen3-reranker"
EMBEDDING_DIMS = 4096


def _is_retryable(exc: BaseException) -> bool:
    if not isinstance(exc, (NetworkError, TimeoutException, HTTPStatusError)):
        return False
    if isinstance(exc, HTTPStatusError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return True


def http_client() -> AsyncClient:
    return AsyncClient(
        transport=AsyncTenacityTransport(
            config=RetryConfig(
                stop=stop_after_attempt(5),
                wait=wait_exponential(multiplier=1, min=1, max=30),
                retry=retry_if_exception(_is_retryable),
                before_sleep=before_sleep_log(logger, logging.WARNING),
            ),
        ),
        timeout=60,
    )


class VLLMChatModel(OpenAIChatModel):
    async def _map_user_prompt(self, part: UserPromptPart) -> ChatCompletionUserMessageParam:
        content: str | list[dict]
        if isinstance(part.content, str):
            content = [{"type": "text", "text": part.content}]
        else:
            content = []
            for item in part.content:
                if isinstance(item, str):
                    content.append({"type": "text", "text": item})
                elif isinstance(item, ImageUrl):
                    content.append({"type": "image_url", "image_url": {"url": item.url}})
                elif isinstance(item, AudioUrl):
                    content.append({"type": "audio_url", "audio_url": {"url": item.url}})
                elif isinstance(item, VideoUrl):
                    content.append({"type": "video_url", "video_url": {"url": item.url}})
                elif isinstance(item, DocumentUrl):
                    content.append({"type": "document_url", "document_url": {"url": item.url}})
                elif isinstance(item, BinaryContent):
                    if item.is_image:
                        content.append({"type": "image_url", "image_url": {"url": item.data_uri}})
                    elif item.is_audio:
                        content.append({"type": "audio_url", "audio_url": {"url": item.data_uri}})
                    elif item.is_video:
                        content.append({"type": "video_url", "video_url": {"url": item.data_uri}})
                    else:
                        content.append({"type": "document_url", "document_url": {"url": item.data_uri}})
                else:
                    raise ValueError(f"Unsupported content item type: {type(item)}")
        return ChatCompletionUserMessageParam(
            role="user",
            content=content,  # type: ignore
        )


def vllm_model_profile(model_name: str) -> ModelProfile:
    return OpenAIModelProfile(
        supports_tools=True,
        supports_image_output=True,
        supports_json_schema_output=True,
        supports_json_object_output=True,
        supports_tool_return_schema=True,
        supports_thinking=True,
        openai_chat_supports_multiple_system_messages=False,
        default_structured_output_mode="native",
        openai_chat_send_back_thinking_parts="field",
        openai_chat_thinking_field="reasoning",
    )


class VLLMProvider(Provider[AsyncOpenAI]):
    @property
    def name(self) -> str:
        return "vllm"

    @property
    def base_url(self) -> str:
        return BASE_URL

    @staticmethod
    def model_profile(model_name: str) -> ModelProfile | None:
        return vllm_model_profile(model_name)

    @property
    def client(self) -> AsyncOpenAI:
        return self._client

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            base_url=BASE_URL,
            api_key=str(API_KEY),
            http_client=http_client(),
        )


def get_model(
    model_name: str | None = None,
) -> Model:
    if model_name is None:
        model_name = CHAT_UID
    return VLLMChatModel(
        model_name=model_name,
        provider=VLLMProvider(),
    )


async def aembed_documents(
    documents: Sequence[Document | str],
) -> list[list[float]]:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    inputs = []
    for document in documents:
        if isinstance(document, Document):
            text = document.content
            img_url = document.image_url
        else:
            text = document
            img_url = None
        content: list[dict] = [{"type": "text", "text": text}]
        if img_url:
            content.append({"type": "image_url", "image_url": {"url": img_url}})
        inputs.append(content)
    payload: dict = {
        "model": EMBEDDING_UID,
        "encoding_format": "float",
        "dimensions": EMBEDDING_DIMS,
        "inputs": inputs,
    }

    async with http_client() as client:
        results = await client.post(f"{BASE_URL}/embed", json=payload, headers=headers)
        results.raise_for_status()
    return [obj["embedding"] for obj in results.json()["data"]]


async def arerank_documents(
    query: str,
    documents: Sequence[Document | str],
    topn: int | None = None,
) -> list[Document]:
    if not documents:
        return []

    inputs = []
    for document in documents:
        if isinstance(document, Document):
            text = document.content
            img_url = document.image_url
        else:
            text = document
            img_url = None
        content: list[dict] = [{"type": "text", "text": text}]
        if img_url:
            content.append({"type": "image_url", "image_url": {"url": img_url}})
        inputs.append({"content": content})

    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    payload = {
        "model": RERANKER_UID,
        "query": query,
        "documents": inputs,
        "return_documents": False,
    }

    async with http_client() as client:
        results = await client.post(f"{BASE_URL}/rerank", json=payload, headers=headers)
        results.raise_for_status()
    score_map = {item["index"]: item["relevance_score"] for item in results.json()["results"]}

    reranked_docs: list[Document] = []
    for idx, src in enumerate(documents):
        score = score_map.get(idx)
        if score is None:
            continue
        if isinstance(src, Document):
            doc = src.model_copy()
            doc.query_score = score
        else:
            doc = Document(content=src, query_score=score)
        reranked_docs.append(doc)

    reranked_docs.sort(key=lambda d: d.query_score or 0, reverse=True)
    if topn is not None:
        reranked_docs = reranked_docs[:topn]
    return reranked_docs

import logging
from collections.abc import Sequence

from httpx import AsyncClient, HTTPError, HTTPStatusError

from .models import Document

logger = logging.getLogger(__name__)

MODEL_URL = "https://nw.lonwell.cn:10001"
EMBEDDING_UID = "qwen3-embedding"
RERANKER_UID = "qwen3-reranker"
EMBEDDING_DIMS = 4096
API_KEY = None
_MAX_RETRIES = 10


async def _retry_post(url: str, json: dict, headers: dict, time_out: float = 60.0) -> dict:
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with AsyncClient(timeout=time_out) as client:
                response = await client.post(url, json=json, headers=headers)
                response.raise_for_status()
                return response.json()
        except HTTPError as exc:
            if attempt == _MAX_RETRIES or (isinstance(exc, HTTPStatusError) and 400 <= exc.response.status_code < 500):
                raise
            logger.warning("HTTP 请求失败 (第 %d/%d 次): %s，重试中", attempt, _MAX_RETRIES, exc)
        except Exception:
            raise
    raise RuntimeError("达到最大重试次数，仍然无法完成请求")


def _build_embedding_input(
    documents: Sequence[Document | str],
    image_urls: Sequence[str | None] | None = None,
    force_text: bool = False,
) -> tuple[str, list[str] | list[dict]]:
    texts: list[str] = []
    images: list[str | None] = []

    for i, d in enumerate(documents):
        text = d.content if isinstance(d, Document) else d
        img_url = image_urls[i] if image_urls and i < len(image_urls) else None

        texts.append(text)
        images.append(img_url)

    if not any(images):
        return ("input", texts)

    messages: list[dict] = []
    for text, img_url in zip(texts, images, strict=True):
        content: list[dict] = [{"type": "text", "text": text}]
        if img_url:
            content.append({"type": "image_url", "image_url": {"url": img_url}})
        messages.append({"role": "user", "content": content})

    return ("messages", messages)


async def aembed_documents(
    documents: Sequence[Document | str],
    image_urls: Sequence[str | None] | None = None,
    force_text: bool = False,
) -> list[list[float]]:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    field_name, field_value = _build_embedding_input(documents, image_urls, force_text=force_text)
    payload: dict = {
        "model": EMBEDDING_UID,
        field_name: field_value,
        "encoding_format": "float",
        "dimensions": EMBEDDING_DIMS,
    }

    results = await _retry_post(f"{MODEL_URL}/v1/embeddings", json=payload, headers=headers)
    return [obj["embedding"] for obj in results["data"]]


def _build_rerank_document(d: Document | str, force_text: bool = False) -> str | dict:
    if isinstance(d, str):
        return d
    return d.content


async def arerank_scores(
    query: str,
    documents: Sequence[Document | str],
    force_text: bool = False,
) -> dict[int, float]:
    if not documents:
        return {}

    doc_inputs = [_build_rerank_document(d, force_text=force_text) for d in documents]

    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    payload = {
        "model": RERANKER_UID,
        "query": query,
        "documents": doc_inputs,
        "return_documents": False,
    }

    results = await _retry_post(f"{MODEL_URL}/v1/rerank", json=payload, headers=headers)
    return {item["index"]: item["relevance_score"] for item in results["results"]}


async def arerank_documents(
    query: str,
    documents: Sequence[Document | str],
    topn: int | None = None,
    force_text: bool = False,
) -> list[Document]:
    if not documents:
        return []

    score_map = await arerank_scores(query, documents, force_text=force_text)

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

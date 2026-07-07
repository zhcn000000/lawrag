"""Content downloader and multi-level parser for national laws.

Downloads law documents from the NPC database via the /download/pc API
and parses them into structured format preserving chapter/section/article hierarchy.

Workflow:
  1. Read law index JSON (from LawIndexSpider), must include bbbs field
  2. For each law, call /download/pc API to get a signed OBS download URL
  3. Download the docx from the signed URL
  4. Convert to text and parse multi-level structure
  5. Save as structured text files
"""

import json
import logging
import re
from os import PathLike
from pathlib import Path
from urllib.parse import unquote, urlparse

import anyio
import httpx
from anyio import Path as AsyncPath
from markitdown import MarkItDown

from lawrag.documents.lawparser import parse_multi_level, write_structured_law
from lawrag.utils.environments import settings

logger = logging.getLogger(__name__)

API_BASE = "https://flk.npc.gov.cn"
DOWNLOAD_API = f"{API_BASE}/law-search/download/pc"

API_HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:136.0) Gecko/20100101 Firefox/136.0",
}

DEFAULT_DOWNLOAD_DIR = settings.DATA_ROOT / "downloaded_laws"
DEFAULT_STRUCTURED_DIR = settings.DATA_ROOT / "structured_laws"
DEFAULT_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_STRUCTURED_DIR.mkdir(parents=True, exist_ok=True)


class LawContentDownloader:
    """Downloads law documents via the NPC API and converts them to text."""

    def __init__(self, download_dir: PathLike | str | None = None) -> None:
        self._download_dir = Path(download_dir) if download_dir is not None else DEFAULT_DOWNLOAD_DIR
        self._download_dir.mkdir(parents=True, exist_ok=True)
        self._md = MarkItDown()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30, headers=API_HEADERS)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_signed_download_url(self, bbbs: str) -> str | None:
        """Call /download/pc to get a signed OBS download URL for the docx file."""
        client = await self._get_client()
        try:
            resp = await client.get(DOWNLOAD_API, params={"format": "docx", "bbbs": bbbs})
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == 200 and data.get("data"):
                return data["data"].get("url")
            logger.warning("Download API returned unexpected data for %s: %s", bbbs, data)
            return None
        except Exception:
            logger.exception("Failed to get download URL for bbbs=%s", bbbs)
            return None

    async def download_document(self, url: str, law_name: str) -> AsyncPath | None:
        """Download a law document from the signed OBS URL."""
        parsed = urlparse(url)
        filename = unquote(Path(parsed.path).name)
        if not filename or "." not in filename:
            safe_name = re.sub(r"[^\w\-]", "_", law_name)
            filename = f"{safe_name}.docx"

        output_path = AsyncPath(self._download_dir / filename)

        if await output_path.exists():
            logger.debug("Already downloaded: %s", output_path)
            return output_path

        try:
            client = await self._get_client()
            resp = await client.get(url, timeout=60)
            resp.raise_for_status()
            await output_path.write_bytes(resp.content)
            logger.info("Downloaded: %s -> %s", law_name, output_path)
            return output_path
        except Exception:
            logger.exception("Failed to download %s from %s", law_name, url)
            return None

    async def convert_to_text(self, file_path: AsyncPath) -> str:
        """Convert a docx/html file to plain text using MarkItDown."""
        ext = file_path.suffix.lower()
        if ext == ".html":
            return await file_path.read_text(encoding="utf-8")
        if ext in (".docx", ".doc"):
            result = self._md.convert(str(file_path))
            return result.text_content
        logger.warning("Unsupported file format: %s", ext)
        return ""

    async def download_and_parse(
        self,
        law_entry: dict,
        *,
        structured_dir: PathLike | str = DEFAULT_STRUCTURED_DIR,
    ) -> str | None:
        """Download a law and parse it into structured text.

        Returns the path to the structured output file, or None on failure.
        """
        output_dir = AsyncPath(structured_dir)
        law_name = law_entry.get("law_name", "")
        bbbs = law_entry.get("bbbs", "")

        if not bbbs:
            logger.warning("No bbbs for %s, skipping", law_name)
            return None

        signed_url = await self.get_signed_download_url(bbbs)
        if not signed_url:
            logger.warning("No download URL for %s", law_name)
            return None
        logger.debug("Downloading %s from %s", law_name, signed_url)
        doc_path = await self.download_document(signed_url, law_name)
        if not doc_path:
            return None

        text = await self.convert_to_text(doc_path)
        if not text:
            return None

        parsed = parse_multi_level(text)
        if not parsed or not parsed.get("articles") and not parsed.get("chapters") and not parsed.get("preamble"):
            logger.warning("Failed to parse %s", law_name)
            return None

        structured_path = await write_structured_law(
            parsed=parsed,
            output_dir=output_dir,
            law_name=law_name,
        )

        return str(structured_path)

    async def process_index(
        self,
        index_path: PathLike | str,
        *,
        structured_dir: PathLike | str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        """Process a law index JSON file, downloading and parsing each law."""
        if structured_dir is None:
            structured_dir = DEFAULT_STRUCTURED_DIR
        idx_path = AsyncPath(index_path)
        if not await idx_path.exists():
            raise FileNotFoundError(f"Index file not found: {idx_path}")

        content = await idx_path.read_text(encoding="utf-8")
        law_list = json.loads(content)

        results: list[dict] = []
        total = len(law_list)

        for i, entry in enumerate(law_list):
            if category and entry.get("category") != category:
                continue
            if entry.get("status") != "有效":
                continue
            if entry.get("law_type") != "法律":
                continue

            try:
                result = await self.download_and_parse(
                    entry,
                    structured_dir=structured_dir,
                )
                results.append({
                    "law_name": entry.get("law_name", ""),
                    "status": "ok" if result else "failed",
                    "output": result,
                })
            except Exception:
                logger.exception("Failed to process %s", entry.get("law_name"))
                results.append({
                    "law_name": entry.get("law_name", ""),
                    "status": "error",
                    "output": None,
                })

            if (i + 1) % 10 == 0:
                logger.info("Progress: %d/%d laws processed", i + 1, total)

            await anyio.sleep(0.5)

        ok_count = sum(1 for r in results if r["status"] == "ok")
        logger.info("Processed %d laws: %d OK, %d failed", total, ok_count, total - ok_count)
        return results


async def run_content_download(
    index_path: PathLike | str,
    *,
    structured_dir: PathLike | str | None = None,
    download_dir: PathLike | str | None = None,
    category: str | None = None,
) -> list[dict]:
    """CLI entry point for content download.

    Usage:
        await run_content_download("data/law_index_flfg.json")
    """
    if structured_dir is None:
        structured_dir = DEFAULT_STRUCTURED_DIR
    if download_dir is None:
        download_dir = DEFAULT_DOWNLOAD_DIR

    downloader = LawContentDownloader(download_dir=download_dir)
    try:
        return await downloader.process_index(
            index_path=index_path,
            structured_dir=structured_dir,
            category=category,
        )
    finally:
        await downloader.close()

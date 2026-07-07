"""Content downloader and multi-level parser for national laws.

Downloads law documents from the NPC database and parses them into
structured format preserving chapter/section/article hierarchy.

Workflow:
  1. Read law index JSON (from LawIndexSpider)
  2. For each law, use Selenium to extract download URL from detail page
  3. Download the document (docx or html)
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

NPC_API_URL = "https://flk.npc.gov.cn/api/"
DETAIL_BASE = "https://flk.npc.gov.cn"
DOC_BASE = "https://wb.flk.npc.gov.cn"

DEFAULT_DOWNLOAD_DIR = settings.DATA_ROOT / "downloaded_laws"
DEFAULT_STRUCTURED_DIR = settings.DATA_ROOT / "structured_laws"


def build_detail_url(raw_url: str) -> str:
    if raw_url.startswith("http"):
        return raw_url
    return DETAIL_BASE + raw_url if raw_url.startswith("/") else f"{DETAIL_BASE}/{raw_url}"


class LawContentDownloader:
    """Downloads law documents using Selenium and converts them to text."""

    def __init__(self, download_dir: PathLike | str = DEFAULT_DOWNLOAD_DIR) -> None:
        self._download_dir = Path(download_dir)
        self._download_dir.mkdir(parents=True, exist_ok=True)
        self._md = MarkItDown()

    async def extract_doc_url_httpx(self, detail_url: str) -> str | None:
        """Attempt to extract document URL"""

        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(detail_url)
                resp.raise_for_status()
                html = resp.text

            docx_match = re.search(r'https?://wb\.flk\.npc\.gov\.cn/[^"\s]+\.docx?', html)
            if docx_match:
                return docx_match.group(0)

            word_match = re.search(r'https?://wb\.flk\.npc\.gov\.cn/[^"\s]+/WORD/[^"\s]+', html)
            if word_match:
                return word_match.group(0)

            return None
        except Exception:
            logger.exception("Failed to fetch %s", detail_url)
            return None

    async def download_document(self, url: str, law_name: str) -> AsyncPath | None:
        """Download a law document from NPC database."""
        parsed = urlparse(url)
        filename = unquote(Path(parsed.path).name)
        if not filename or "." not in filename:
            safe_name = re.sub(r"[^\w\-]", "_", law_name)
            if "texthtml" in url:
                filename = f"{safe_name}.html"
            else:
                filename = f"{safe_name}.docx"

        output_path = AsyncPath(self._download_dir / filename)

        if await output_path.exists():
            logger.debug("Already downloaded: %s", output_path)
            return output_path

        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                resp = await client.get(url)
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
        doc_url: str | None = None,
    ) -> str | None:
        """Download a law and parse it into structured text.

        Returns the path to the structured output file, or None on failure.
        """
        output_dir = AsyncPath(structured_dir)
        law_name = law_entry.get("law_name", "")
        detail_url = law_entry.get("detail_url", "")

        if not doc_url and detail_url:
            doc_url = await self.extract_doc_url_httpx(detail_url)

        if not doc_url:
            logger.warning("No download URL for %s", law_name)
            return None

        doc_path = await self.download_document(doc_url, law_name)
        if not doc_path:
            return None

        text = await self.convert_to_text(doc_path)
        if not text:
            return None

        parsed = parse_multi_level(text)
        if not parsed or not parsed.get("articles") and not parsed.get("preamble"):
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
        structured_dir: PathLike | str = DEFAULT_STRUCTURED_DIR,
        category: str | None = None,
    ) -> list[dict]:
        """Process a law index JSON file, downloading and parsing each law."""

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
    structured_dir: PathLike | str = DEFAULT_STRUCTURED_DIR,
    download_dir: PathLike | str = DEFAULT_DOWNLOAD_DIR,
    category: str | None = None,
) -> list[dict]:
    """CLI entry point for content download.

    Usage:
        await run_content_download("data/law_index_flfg.json")
    """
    downloader = LawContentDownloader(download_dir=download_dir)
    return await downloader.process_index(
        index_path=index_path,
        structured_dir=structured_dir,
        category=category,
    )

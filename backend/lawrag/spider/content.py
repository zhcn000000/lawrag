"""Content download and multi-level parser for national laws.

Downloads law documents from the NPC database via the /download/pc API
and parses them into structured format preserving chapter/section/article hierarchy.

Workflow:
  1. Read law index JSON (from LawIndexSpider), must include bbbs field
  2. Use Scrapy to download all docx files via signed OBS URLs
  3. Convert to text and parse multi-level structure
  4. Save as structured text files
"""

import logging
from pathlib import Path

from lawrag.utils.environments import settings

logger = logging.getLogger(__name__)

DEFAULT_DOWNLOAD_DIR = settings.DATA_ROOT / "downloaded_laws"
DEFAULT_STRUCTURED_DIR = settings.DATA_ROOT / "structured_laws"
DEFAULT_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_STRUCTURED_DIR.mkdir(parents=True, exist_ok=True)


async def run_content_download(
    index_path: str | Path,
    *,
    structured_dir: str | Path | None = None,
    download_dir: str | Path | None = None,
    category: str | None = None,
) -> list[dict]:
    """CLI entry point for content download.

    Usage:
        await run_content_download("data/law_index_flfg.json")
    """
    from lawrag.spider.runner import run_content_download as _run

    return await _run(
        index_path=index_path,
        structured_dir=structured_dir or DEFAULT_STRUCTURED_DIR,
        download_dir=download_dir or DEFAULT_DOWNLOAD_DIR,
        category=category,
    )

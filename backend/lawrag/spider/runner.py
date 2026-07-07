"""Async law spider runner using Scrapy's native asyncio support (AsyncCrawlerRunner).

Uses TWISTED_REACTOR_ENABLED=False for pure asyncio mode without a Twisted reactor.
"""

import json
import logging
from pathlib import Path
from typing import Any

from scrapy.crawler import AsyncCrawlerRunner

from lawrag.spider.content_spider import ContentDownloadSpider
from lawrag.spider.law_spider import LawIndexSpider
from lawrag.utils.environments import settings as env_settings

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS: dict[str, Any] = {
    "BOT_NAME": "lawrag_spider",
    "ROBOTSTXT_OBEY": False,
    "RANDOMIZE_DOWNLOAD_DELAY": True,
    "LOG_LEVEL": "INFO",
    "COOKIES_ENABLED": False,
    "TELNETCONSOLE_ENABLED": False,
    "RETRY_ENABLED": True,
    "RETRY_TIMES": 3,
    "DOWNLOAD_TIMEOUT": 30,
    "DEFAULT_REQUEST_HEADERS": {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    },
    "ITEM_PIPELINES": {
        "lawrag.spider.pipelines.LawIndexPipeline": 300,
    },
    "TWISTED_REACTOR_ENABLED": False,
}

LAW_INDEX_SETTINGS: dict[str, Any] = DEFAULT_SETTINGS.copy()
LAW_INDEX_SETTINGS.update({
    "DOWNLOAD_DELAY": 1.0,
    "CONCURRENT_REQUESTS": 8,
    "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
    "ITEM_PIPELINES": {
        "lawrag.spider.pipelines.LawIndexPipeline": 300,
    },
})

CONTENT_DOWNLOAD_SETTINGS: dict[str, Any] = DEFAULT_SETTINGS.copy()
CONTENT_DOWNLOAD_SETTINGS.update({
    "DOWNLOAD_DELAY": 0.5,
    "CONCURRENT_REQUESTS": 4,
    "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
    "ITEM_PIPELINES": {
        "lawrag.spider.pipelines.ContentDownloadPipeline": 300,
    },
})


async def run_law_index_spider(
    *,
    category: str = "all",
    output: Path | None = None,
    extra_settings: dict[str, Any] | None = None,
) -> None:
    settings = LAW_INDEX_SETTINGS.copy()
    if extra_settings:
        settings.update(extra_settings)

    output_path = output or (env_settings.DATA_ROOT / "law_index" / "law_index.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    settings["LAW_INDEX_PATH"] = output_path

    runner = AsyncCrawlerRunner(settings)
    await runner.crawl(LawIndexSpider, category=category)


async def run_content_download(
    index_path: str | Path,
    *,
    structured_dir: str | Path | None = None,
    download_dir: str | Path | None = None,
    category: str | None = None,
) -> list[dict]:
    """Run the Scrapy content download spider that downloads, converts, and parses laws.

    Returns a list of result dicts: {"law_name": ..., "status": "ok"/"failed"/"error", "output": path}
    """
    settings = CONTENT_DOWNLOAD_SETTINGS.copy()

    download_path = Path(download_dir or env_settings.DATA_ROOT / "data" / "downloaded_laws")
    structured_path = Path(structured_dir or env_settings.DATA_ROOT / "data" / "structured_laws")

    manifest_path = download_path / ".manifest.json"
    settings["LAW_CONTENT_DOWNLOAD_DIR"] = download_path
    settings["LAW_CONTENT_STRUCTURED_DIR"] = structured_path
    settings["LAW_CONTENT_MANIFEST_PATH"] = manifest_path

    runner = AsyncCrawlerRunner(settings)
    await runner.crawl(ContentDownloadSpider, index_path=str(index_path), category=category)

    if not manifest_path.exists():
        logger.warning("No manifest found — no files were downloaded.")
        return []

    return json.loads(manifest_path.read_text(encoding="utf-8"))

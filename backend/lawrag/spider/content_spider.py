import json
import logging
import re
from collections.abc import AsyncIterator, Generator
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlencode, urlparse

from anyio import Path as AsyncPath
from scrapy import Request, Spider
from scrapy.http.response import Response

from lawrag.spider.items import LawDownloadItem

logger = logging.getLogger(__name__)

DOWNLOAD_API = "https://flk.npc.gov.cn/law-search/download/pc"


class ContentDownloadSpider(Spider):
    """Spider that downloads law documents via the NPC signed-URL API.

    Usage:
        scrapy crawl content_download -a index_path=data/law_index.json
    """

    name = "content_download"

    def __init__(self, index_path: str = "", category: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._index_path = index_path
        self._category: str | None = category
        self._total = 0
        self._downloaded = 0

    async def start(self) -> AsyncIterator[Request]:

        if not self._index_path:
            logger.error("No index_path provided")
            return

        idx = AsyncPath(self._index_path)
        if not await idx.exists():
            logger.error("Index file not found: %s", self._index_path)
            return

        content = await idx.read_text(encoding="utf-8")
        law_list: list[dict] = json.loads(content)
        logger.info("Loaded %d laws from index: %s", len(law_list), self._index_path)
        structured_dir = AsyncPath(self.settings.get("LAW_CONTENT_STRUCTURED_DIR"))
        await structured_dir.mkdir(parents=True, exist_ok=True)
        current_files = {f.stem async for f in structured_dir.iterdir()}
        for entry in law_list:
            if self._category and entry.get("category") != self._category:
                continue

            if entry.get("status") != "有效":
                continue

            if entry.get("law_type") not in {
                "宪法",
                "法律",
                # "行政法规",
                # "监察法规",
            }:
                continue

            if entry.get("law_type") == "宪法":
                if entry.get("law_name") != "中华人民共和国宪法（2018年修正文本）":
                    continue
                else:
                    entry["law_name"] = "中华人民共和国宪法"

            if entry.get("law_name") in current_files:
                logger.debug("Skipping already downloaded: %s", entry.get("law_name"))
                continue

            bbbs = entry.get("law_id", "") or entry.get("bbbs", "")
            law_name = entry.get("law_name", "")

            if not bbbs:
                logger.warning("No bbbs for %s, skipping", law_name)
                continue

            params = urlencode({"format": "docx", "bbbs": bbbs})
            url = f"{DOWNLOAD_API}?{params}"

            self._total += 1

            yield Request(
                url=url,
                method="GET",
                callback=self.parse_signed_url,
                meta={"bbbs": bbbs, "law_name": law_name},
                dont_filter=True,
            )

    def parse_signed_url(self, response: Response) -> Generator[Request]:
        law_name: str = response.meta["law_name"]

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.exception("JSON decode error for %s", law_name)
            return

        if data.get("code") != 200 or not data.get("data"):
            logger.warning("Unexpected API response for %s: %s", law_name, data)
            return

        signed_url = data["data"].get("url")
        if not signed_url:
            logger.warning("No download URL for %s", law_name)
            return

        parsed = urlparse(signed_url)
        filename = unquote(Path(parsed.path).name)
        if not filename or "." not in filename:
            safe_name = re.sub(r"[^\w\-]", "_", law_name)
            filename = f"{safe_name}.docx"

        yield Request(
            url=signed_url,
            method="GET",
            priority=1,
            callback=self.parse_document,
            meta={**response.meta, "filename": filename},
            dont_filter=True,
        )

    def parse_document(self, response: Response) -> Generator[LawDownloadItem]:
        self._downloaded += 1
        if self._downloaded % 10 == 0:
            logger.info("Progress: %d/%d laws downloaded", self._downloaded, self._total)

        yield LawDownloadItem(
            law_id=response.meta["bbbs"],
            law_name=response.meta["law_name"],
            file_content=response.body,
            filename=response.meta["filename"],
            extension=Path(response.meta["filename"]).suffix.lower(),
        )

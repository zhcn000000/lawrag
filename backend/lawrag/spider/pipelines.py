import logging
from pathlib import Path

from anyio import Path as AsyncPath
from asyncer import asyncify
from markitdown import MarkItDown

from lawrag.database.law_index import LawIndexManager
from lawrag.documents.lawparser import has_parsed_content, parse_multi_level
from lawrag.environments import settings as env_settings
from lawrag.spider.items import LawDownloadItem, LawIndexItem

logger = logging.getLogger(__name__)


class ContentDownloadPipeline:
    """Save downloaded law files to disk, convert to text, parse, and store structured output in the database."""

    download_dir: AsyncPath | None = None
    md: MarkItDown = MarkItDown()

    def __init__(self) -> None:
        self._results: list[dict] = []
        self._lm = LawIndexManager()

    @classmethod
    def from_crawler(cls, crawler):
        pipeline = cls()
        settings = crawler.settings
        pipeline.download_dir = AsyncPath(
            settings.get("LAW_CONTENT_DOWNLOAD_DIR", env_settings.DATA_ROOT / "downloaded_laws"),
        )
        return pipeline

    async def process_item(self, item: LawDownloadItem) -> LawDownloadItem:
        assert self.download_dir is not None, "download_dir must be set"

        await self.download_dir.mkdir(parents=True, exist_ok=True)

        law_name: str = item["law_name"]
        law_id: str = item["law_id"]
        output_path: AsyncPath = self.download_dir / item["filename"]

        if not await output_path.exists():
            await output_path.write_bytes(item["file_content"])
            logger.info("Downloaded: %s -> %s", law_name, output_path)

        try:
            ext = item["extension"]
            if ext == ".html":
                text = await output_path.read_text(encoding="utf-8")
            elif ext in (".docx", ".doc"):
                result = await asyncify(self.md.convert)(Path(output_path))
                text = result.text_content
            else:
                logger.warning("Unsupported format %s for %s", ext, law_name)
                self._results.append({"law_name": law_name, "status": "failed", "output": None})
                return item

            if not text:
                self._results.append({"law_name": law_name, "status": "failed", "output": None})
                return item

            await self._lm.aupsert_raw(law_id, text)

            parsed = parse_multi_level(text)
            if not has_parsed_content(parsed):
                logger.warning("Failed to parse %s", law_name)
                self._results.append({"law_name": law_name, "status": "failed", "output": None})
                return item

            await self._lm.aupsert_structured(law_id, parsed)
            self._results.append({"law_name": law_name, "status": "ok", "output": str(output_path)})
        except Exception:
            logger.exception("Failed to process %s", law_name)
            self._results.append({"law_name": law_name, "status": "error", "output": None})

        return item

    def close_spider(self) -> None:
        ok = sum(1 for r in self._results if r["status"] == "ok")
        logger.info("Content download done: %d OK, %d total", ok, len(self._results))


class LawIndexPipeline:
    """Pipeline that stores law index items directly in the database."""

    def __init__(self) -> None:
        self._lm = LawIndexManager()

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    async def process_item(self, item: LawIndexItem) -> LawIndexItem:
        await self._lm.aupsert(
            law_id=item.get("law_id", ""),
            law_name=item.get("law_name", ""),
            office=item.get("office", ""),
            publish_date=item.get("publish_date", ""),
            expiry_date=item.get("expiry_date", ""),
            law_type=item.get("law_type", ""),
            status=item.get("status", ""),
            detail_url=item.get("detail_url", ""),
            index_number=item.get("index_number", ""),
        )
        return item

    async def close_spider(self) -> None:
        pass

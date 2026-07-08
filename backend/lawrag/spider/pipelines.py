"""Pipelines for law spider."""

import json
import logging
from pathlib import Path

from markitdown import MarkItDown
from scrapy import Spider

from lawrag.documents.lawparser import parse_multi_level, write_structured_law
from lawrag.spider.items import LawDownloadItem, LawIndexItem
from lawrag.utils.environments import settings as env_settings

logger = logging.getLogger(__name__)


class ContentDownloadPipeline:
    """Save downloaded law files to disk, convert to text, parse, and write structured output."""

    download_dir: Path | None = None
    structured_dir: Path | None = None
    raw_dir: Path | None = None
    md: MarkItDown = MarkItDown()

    def __init__(self) -> None:
        self._results: list[dict] = []

    @classmethod
    def from_crawler(cls, crawler):
        pipeline = cls()
        settings = crawler.settings
        pipeline.download_dir = Path(
            settings.get("LAW_CONTENT_DOWNLOAD_DIR", env_settings.DATA_ROOT / "downloaded_laws")
        )
        pipeline.structured_dir = Path(
            settings.get("LAW_CONTENT_STRUCTURED_DIR", env_settings.DATA_ROOT / "structured_laws")
        )
        pipeline.raw_dir = Path(settings.get("LAW_CONTENT_RAW_DIR", env_settings.DATA_ROOT / "raw_laws"))

        for dir_path in (pipeline.download_dir, pipeline.structured_dir, pipeline.raw_dir):
            dir_path.mkdir(parents=True, exist_ok=True)

        return pipeline

    def process_item(self, item: LawDownloadItem) -> LawDownloadItem:
        assert self.download_dir is not None, "download_dir must be set"
        assert self.structured_dir is not None, "structured_dir must be set"
        assert self.raw_dir is not None, "raw_dir must be set"

        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.structured_dir.mkdir(parents=True, exist_ok=True)

        law_name: str = item["law_name"]
        output_path = self.download_dir / item["filename"]

        if not output_path.exists():
            output_path.write_bytes(item["file_content"])
            logger.info("Downloaded: %s -> %s", law_name, output_path)

        try:
            ext = item["extension"]
            if ext == ".html":
                text = output_path.read_text(encoding="utf-8")
            elif ext in (".docx", ".doc"):
                result = self.md.convert(str(output_path))
                text = result.text_content
            else:
                logger.warning("Unsupported format %s for %s", ext, law_name)
                self._results.append({"law_name": law_name, "status": "failed", "output": None})
                return item

            if not text:
                self._results.append({"law_name": law_name, "status": "failed", "output": None})
                return item
            (self.raw_dir / f"{law_name}.txt").write_text(text, encoding="utf-8")

            parsed = parse_multi_level(text)
            if not parsed or (not parsed.get("articles") and not parsed.get("chapters") and not parsed.get("preamble")):
                logger.warning("Failed to parse %s", law_name)
                self._results.append({"law_name": law_name, "status": "failed", "output": None})
                return item

            structured = write_structured_law(parsed=parsed, output_dir=self.structured_dir, law_name=law_name)
            self._results.append({"law_name": law_name, "status": "ok", "output": str(structured)})
        except Exception:
            logger.exception("Failed to process %s", law_name)
            self._results.append({"law_name": law_name, "status": "error", "output": None})

        return item

    def close_spider(self, spider: Spider) -> None:
        manifest_path = spider.crawler.settings.get("LAW_CONTENT_MANIFEST_PATH", "")
        if manifest_path and self._results:
            output = Path(manifest_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(self._results, ensure_ascii=False, indent=2), encoding="utf-8")
            ok = sum(1 for r in self._results if r["status"] == "ok")
            logger.info("Content download done: %d OK, %d total -> %s", ok, len(self._results), output)


class LawIndexPipeline:
    """Pipeline that collects law index items and incrementally upserts to a single JSON file."""

    def __init__(self) -> None:
        self._items: dict[str, dict] = {}

    def process_item(self, item: LawIndexItem) -> LawIndexItem:
        law_id = item.get("law_id", "")
        entry = {
            "law_id": law_id,
            "law_name": item.get("law_name", ""),
            "office": item.get("office", ""),
            "publish_date": item.get("publish_date", ""),
            "expiry_date": item.get("expiry_date", ""),
            "law_type": item.get("law_type", ""),
            "status": item.get("status", ""),
            "detail_url": item.get("detail_url", ""),
            "category": item.get("category", ""),
            "index_number": item.get("index_number", ""),
        }
        if law_id:
            self._items[law_id] = entry
        return item

    def close_spider(self, spider: Spider) -> None:
        if not self._items:
            return

        output_path = spider.crawler.settings.get(
            "LAW_INDEX_PATH",
            env_settings.DATA_ROOT / "law_index" / "law_index.json",
        )
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        existing: dict[str, dict] = {}
        if output_file.exists():
            try:
                with output_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                for entry in data:
                    lid = entry.get("law_id", "")
                    if lid:
                        existing[lid] = entry
                logger.info("Loaded %d existing entries from %s", len(existing), output_file)
            except json.JSONDecodeError, OSError:
                logger.warning("Could not read existing %s, starting fresh", output_file)

        merged = {**existing, **self._items}
        new_count = len(self._items)
        updated_count = sum(1 for lid in self._items if lid in existing)
        total_count = len(merged)
        logger.info(
            "LawIndexPipeline: %d new, %d updated, %d total entries -> %s",
            new_count - updated_count,
            updated_count,
            total_count,
            output_file,
        )

        entries = sorted(merged.values(), key=lambda e: (e.get("category", ""), e.get("law_name", "")))
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

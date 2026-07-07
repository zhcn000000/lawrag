"""Pipelines for law spider."""

import json
import logging
from pathlib import Path

from scrapy import Spider

from lawrag.spider.items import LawIndexItem

logger = logging.getLogger(__name__)


class LawIndexPipeline:
    """Pipeline that collects law index items and incrementally upserts to a single JSON file."""

    def __init__(self) -> None:
        self._items: dict[str, dict] = {}

    def process_item(self, item: LawIndexItem, spider: Spider) -> LawIndexItem:
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
            "data/law_index/law_index.json",
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

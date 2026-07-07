"""Pipelines for law spider."""

import json
import logging
import pathlib

from scrapy import Spider

from lawrag.spider.items import LawIndexItem

logger = logging.getLogger(__name__)


class LawIndexPipeline:
    """Pipeline that collects law index items and exports them."""

    def __init__(self) -> None:
        self._items: dict[str, list[dict]] = {}

    def process_item(self, item: LawIndexItem, spider: Spider) -> LawIndexItem:
        cat = item.get("category", "unknown")
        if cat not in self._items:
            self._items[cat] = []

        self._items[cat].append({
            "index_number": item.get("index_number", ""),
            "law_name": item.get("law_name", ""),
            "office": item.get("office", ""),
            "publish_date": item.get("publish_date", ""),
            "expiry_date": item.get("expiry_date", ""),
            "law_type": item.get("law_type", ""),
            "status": item.get("status", ""),
            "detail_url": item.get("detail_url", ""),
            "category": item.get("category", ""),
        })
        return item

    def close_spider(self, spider: Spider) -> None:
        if not self._items:
            return

        for cat, items in self._items.items():
            total = len(items)
            logger.info("LawIndexPipeline: collected %d items for category '%s'", total, cat)

            if hasattr(spider, "crawler"):
                feed_uri = spider.crawler.settings.get("LAW_INDEX_OUTPUT")
                if feed_uri:
                    output_path = feed_uri.replace("{category}", cat)
                    with pathlib.Path(output_path).open("w", encoding="utf-8") as f:
                        json.dump(items, f, ensure_ascii=False, indent=2)
                    logger.info("Exported %d laws for '%s' to %s", total, cat, output_path)

"""Scrapy items for law spider."""

from scrapy.item import Field, Item


class LawIndexItem(Item):
    """A law entry from the NPC API index."""

    law_name: Field = Field()
    office: Field = Field()
    publish_date: Field = Field()
    expiry_date: Field = Field()
    law_type: Field = Field()
    status: Field = Field()
    detail_url: Field = Field()
    category: Field = Field()
    index_number: Field = Field()

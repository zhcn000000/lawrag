from collections import Counter

import mmh3
from asyncer import asyncify

from .models import Document, get_nlp

BM25_VOCAB_SIZE = 1_000_000


async def atokenize_document(content: str | Document) -> Counter[int]:
    if isinstance(content, Document):
        content = content.content
    nlp = get_nlp()
    doc = await asyncify(nlp)(content)
    ids = [abs(mmh3.hash(token.text)) % BM25_VOCAB_SIZE for token in doc if not token.is_space]
    return Counter(ids)

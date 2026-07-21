from collections import Counter
from collections.abc import AsyncIterator, Sequence
from functools import lru_cache

import mmh3
import spacy
from asyncer import asyncify

from lawrag.documents.models import Document

BM25_VOCAB_SIZE = 1_000_000


@lru_cache(maxsize=1)
def get_nlp():
    return spacy.load("zh_core_web_trf")


async def asplit_document(
    document: Document,
    chunk_size: int = 4096,
    chunk_overlap: int = 128,
) -> AsyncIterator[Document]:
    nlp = get_nlp()
    doc = await asyncify(nlp)(document.content)
    sents = list(doc.sents)
    if not sents:
        return

    current_text = ""
    current_tokens = 0
    overlap_sentences: list[tuple[str, int]] = []

    for sent in sents:
        sent_text = sent.text
        sent_tokens = len(sent)
        if current_tokens + sent_tokens <= chunk_size:
            current_text += sent_text
            current_tokens += sent_tokens
            overlap_sentences.append((sent_text, sent_tokens))
        else:
            if current_text:
                yield Document(
                    content=current_text,
                    name=document.name,
                )
            overlap_text = ""
            overlap_token_count = 0
            overlap_sent_list: list[tuple[str, int]] = []
            for os_text, os_tokens in reversed(overlap_sentences):
                if overlap_token_count + os_tokens <= chunk_overlap:
                    overlap_text = os_text + overlap_text
                    overlap_token_count += os_tokens
                    overlap_sent_list.insert(0, (os_text, os_tokens))
                else:
                    break

            current_text = overlap_text + sent_text
            current_tokens = overlap_token_count + sent_tokens
            overlap_sentences = [*overlap_sent_list, (sent_text, sent_tokens)]

    if current_text:
        yield Document(
            content=current_text,
            name=document.name,
        )


async def atokenize_documents(documents: Sequence[Document | str]) -> list[Document]:
    results: list[Document] = []
    for document in documents:
        if isinstance(document, Document):
            content = document.content
        else:
            content = document
        nlp = get_nlp()
        doc = await asyncify(nlp)(content)
        if isinstance(document, Document):
            document.token_count = dict(Counter(mmh3.hash(word.text, signed=False) % BM25_VOCAB_SIZE for word in doc))
            results.append(document)
        else:
            docum = Document(
                content=content,
                token_count=dict(Counter(mmh3.hash(word.text, signed=False) % BM25_VOCAB_SIZE for word in doc)),
            )
            results.append(docum)
    return results

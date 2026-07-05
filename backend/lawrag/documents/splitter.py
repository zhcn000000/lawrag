from collections.abc import AsyncIterator

from asyncer import asyncify

from lawrag.documents.models import Document, get_nlp


async def asplit_content(content: str, chunk_size: int = 512, chunk_overlap: int = 32) -> AsyncIterator[str]:
    nlp = get_nlp()
    doc = await asyncify(nlp)(content)
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
                yield current_text
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
            overlap_sentences = overlap_sent_list + [(sent_text, sent_tokens)]

    if current_text:
        yield current_text


async def asplit_document(
    document: Document,
    chunk_size: int = 512,
    chunk_overlap: int = 32,
) -> AsyncIterator[Document]:
    async for chunk in asplit_content(document.content, chunk_size, chunk_overlap):
        yield Document(
            content=chunk,
            name=document.name,
            link=document.link,
            metadata=document.metadata,
            entities=document.entities,
            page_index=document.page_index,
            image_url=document.image_url,
        )

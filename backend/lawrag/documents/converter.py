import re
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from asyncer import asyncify
from markitdown import MarkItDown

from .models import Document


@lru_cache(maxsize=1)
def get_markitdown_converter() -> MarkItDown:
    converter = MarkItDown()
    return converter


async def aconvert_file(uri: Path | str | BytesIO) -> Document:
    converter = get_markitdown_converter()
    if isinstance(uri, Path):
        result = await asyncify(converter.convert_local)(uri)
    elif isinstance(uri, BytesIO):
        result = await asyncify(converter.convert_stream)(uri)
    elif isinstance(uri, str) and re.match(r"^https?://", uri):
        result = await asyncify(converter.convert_url)(uri)
    elif (isinstance(uri, str) and re.match(r"^data:.*;base64,", uri)) or re.match(r"^file://", uri):
        result = await asyncify(converter.convert_uri)(uri)
    else:
        raise TypeError("Unsupported URI type. Must be a file path, URL, data URI, or file URI.")
    return Document(
        content=result.markdown,
    )

from __future__ import annotations

import re
from pathlib import Path

CN_NUM_MAP: dict[str, int] = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "百": 100,
    "千": 1000,
}


def cn_to_int(cn: str) -> int:
    """中文数字转整数, 例如 '一百二十三' → 123, '四十二' → 42"""
    if not cn:
        return 0
    result = 0
    section = 0
    for char in cn:
        val = CN_NUM_MAP.get(char)
        if val is None:
            continue
        if val >= 10:
            if section == 0:
                section = 1
            result += section * val
            section = 0
        else:
            section = val
    result += section
    return result


FORMAT_B_PATTERN = re.compile(
    r"^《(.+?)》第([零一二三四五六七八九十百千]+)条规定，(.+)。$",
)


def parse_format_b_line(line: str) -> tuple[str, int, str] | None:
    """解析格式B的一行法条: 《XX法》第X条规定，{内容}。"""
    m = FORMAT_B_PATTERN.match(line.strip())
    if m is None:
        return None
    law_name = m.group(1)
    article_cn = m.group(2)
    content = m.group(3)
    article_num = cn_to_int(article_cn)
    return law_name, article_num, content


def parse_format_b(content: str) -> list[tuple[str, int, str]]:
    """解析格式B的全文(每行一条法条)"""
    results: list[tuple[str, int, str]] = []
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        parsed = parse_format_b_line(stripped)
        if parsed:
            results.append(parsed)
    return results


CHAPTER_PATTERN = re.compile(r"^第([零一二三四五六七八九十百千]+)章\s*(.+)$")
SECTION_PATTERN = re.compile(r"^第([零一二三四五六七八九十百千]+)节\s*(.+)$")
ARTICLE_PATTERN = re.compile(r"^第([零一二三四五六七八九十百千]+)条\s*(.*)$")
ARTICLE_SPLIT_PATTERN = re.compile(r"(第[零一二三四五六七八九十百千]+条)")


def parse_format_a(content: str) -> list[tuple[str, int, str]]:
    """解析格式A - 宪法格式(有章节标题, 法条可跨多行, 一行可有多条法条)

    返回 [(law_name, article_number, content), ...]
    article_number=0 表示序言
    """

    def _split_multi_article_lines(lines: list[str]) -> list[str]:
        """将一行中的多条法条拆分为独立行"""
        result: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                result.append("")
                continue
            if CHAPTER_PATTERN.match(stripped) or SECTION_PATTERN.match(stripped) or stripped in ("序 言", "目 录"):
                result.append(stripped)
                continue

            parts = list(ARTICLE_SPLIT_PATTERN.finditer(stripped))
            if not parts:
                result.append(stripped)
                continue

            for match in parts:
                start = match.start()
                next_start = (
                    parts[parts.index(match) + 1].start() if parts.index(match) + 1 < len(parts) else len(stripped)
                )
                segment = stripped[start:next_start].strip()
                result.append(segment)
        return result

    lines = content.splitlines()
    lines = _split_multi_article_lines(lines)
    results: list[tuple[str, int, str]] = []
    law_name = "中华人民共和国宪法"

    # 跳过标题块 (第1-2行) 和目录 (到第一个 '第X章' 或 '序 言' 为止)
    body_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if CHAPTER_PATTERN.match(stripped) or stripped == "序 言":
            body_start = i
            break

    i = body_start
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue

        if stripped == "序 言":
            # 序言正文从下一行开始, 积累到遇到下一章标题
            preamble_parts: list[str] = []
            i += 1
            while i < len(lines):
                stripped2 = lines[i].strip()
                if not stripped2 or stripped2 == "目 录" or stripped2 == "序 言":
                    i += 1
                    continue
                if CHAPTER_PATTERN.match(stripped2):
                    break
                preamble_parts.append(stripped2)
                i += 1
            if preamble_parts:
                results.append((law_name, 0, "".join(preamble_parts)))
            continue

        chapter_match = CHAPTER_PATTERN.match(stripped)
        section_match = SECTION_PATTERN.match(stripped)
        article_match = ARTICLE_PATTERN.match(stripped)

        if article_match:
            article_cn = article_match.group(1)
            article_num = cn_to_int(article_cn)
            first_part = article_match.group(2)

            article_content = first_part or ""
            i += 1
            # 继续收集后续行直到遇到下一章/节/条标题
            while i < len(lines):
                next_line = lines[i].strip()
                if not next_line:
                    i += 1
                    continue
                if (
                    CHAPTER_PATTERN.match(next_line)
                    or SECTION_PATTERN.match(next_line)
                    or ARTICLE_PATTERN.match(next_line)
                ):
                    break
                article_content += next_line
                i += 1
            results.append((law_name, article_num, article_content.strip()))
            continue

        if chapter_match or section_match:
            i += 1
            continue

        i += 1

    return results


def parse_content(content: str, law_name_override: str | None = None) -> list[tuple[str, int, str]]:
    """自动判断格式并解析法律全文

    Returns:
        [(law_name, article_number, content), ...]

    """
    if content.strip().startswith("中华人民共和国宪法"):
        return parse_format_a(content)

    result = parse_format_b(content)
    if result and law_name_override:
        return [(law_name_override, num, content) for _, num, content in result]
    return result


def parse_multi_level(content: str) -> dict:
    """Parse a full law text preserving multi-level chapter/section/article hierarchy.

    Handles format from NPC database docx/HTML conversion (via markitdown).
    Detects:
      - 序言 (preamble) for constitution
      - 第X章 标题 (chapter headings)
      - 第X节 标题 (section headings)
      - 第X条 内容 (article text, possibly multi-line)

    Returns:
        {
            "law_name": "中华人民共和国宪法",
            "preamble": "..." | None,
            "chapters": [
                {
                    "number": 1,
                    "title": "总纲",
                    "sections": [
                        {
                            "number": 1,
                            "title": "人民代表大会",
                            "articles": [
                                {"number": 1, "content": "..."},
                                ...
                            ]
                        }
                    ],
                    "articles": [...]  # direct articles when no sections
                }
            ],
            "articles": [...]  # top-level articles when no chapters
        }
    """
    lines = content.splitlines()

    preamble_parts: list[str] = []
    preamble_active = False

    chapters: list[dict] = []
    current_chapter: dict | None = None
    current_section: dict | None = None
    current_articles: list[dict] = []
    top_level_articles: list[dict] = []
    law_name = ""

    article_buffer: list[str] = []
    article_number: int | None = None

    # Try to detect law name from title line
    for line in lines[:10]:
        stripped = line.strip()
        if stripped.startswith("中华人民共和国") and "法" in stripped and not stripped.startswith("第"):
            law_name = stripped.split(" ")[0].split("\t")[0]
            break

    def _flush_article() -> None:
        nonlocal article_buffer, article_number
        if article_number is not None and article_buffer:
            content = "".join(article_buffer).strip()
            article = {"number": article_number, "content": content}
            current_articles.append(article)
        article_buffer = []
        article_number = None

    def _flush_section() -> None:
        nonlocal current_section
        _flush_article()
        if current_section is not None:
            current_section["articles"] = list(current_articles)
            current_articles.clear()
            if current_chapter is not None:
                current_chapter.setdefault("sections", []).append(current_section)
            current_section = None

    def _flush_chapter() -> None:
        nonlocal current_chapter
        _flush_section()
        if current_chapter is not None:
            if current_articles:
                current_chapter["articles"] = list(current_articles)
                current_articles.clear()
            else:
                current_chapter["articles"] = []
            chapters.append(current_chapter)
        current_chapter = None

    def _is_heading(stripped: str) -> bool:
        return bool(
            CHAPTER_PATTERN.match(stripped) or SECTION_PATTERN.match(stripped) or stripped == "序 言",
        )

    # Detect and skip table of contents
    toc_end = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped in ("目 录", "目录"):
            toc_end = i
            break

    if toc_end > 0:
        body_start = toc_end + 1
        for j in range(toc_end + 1, len(lines)):
            stripped = lines[j].strip()
            if not stripped:
                continue
            if not _is_heading(stripped):
                for k in range(j - 1, toc_end, -1):
                    if lines[k].strip():
                        body_start = k
                        break
                break
        body_lines = lines[body_start:]
    else:
        body_lines = lines

    # Line splitting pattern: only split on article and chapter boundaries
    # Section headings naturally appear on their own lines, so we don't split on 第X节
    _line_split_pattern = re.compile(r"(第[零一二三四五六七八九十百千]+(?:条|章))")

    # Split lines that contain multiple articles/chapters on the same line
    def _split_multi_articles(lines_input: list[str]) -> list[str]:
        result: list[str] = []
        for line in lines_input:
            stripped = line.strip()
            if not stripped:
                result.append("")
                continue

            parts = list(_line_split_pattern.finditer(stripped))
            if not parts:
                result.append(stripped)
                continue

            for idx_match, match in enumerate(parts):
                start = match.start()
                next_start = parts[idx_match + 1].start() if idx_match + 1 < len(parts) else len(stripped)
                segment = stripped[start:next_start].strip()
                result.append(segment)
        return result

    body_lines = _split_multi_articles(body_lines)

    def _is_likely_heading(stripped: str) -> tuple[bool, str]:
        """Check if a line starting with 第X章/节 looks like a real heading or article text."""
        ch_m = CHAPTER_PATTERN.match(stripped)
        if ch_m:
            title = ch_m.group(2).strip()
            if not title:
                return False, ""
            if title[0] in "的第之中。，、；":
                return False, ""
            return True, "chapter"
        sec_m = SECTION_PATTERN.match(stripped)
        if sec_m:
            title = sec_m.group(2).strip()
            if not title:
                return False, ""
            if title[0] in "的第之中。，、；":
                return False, ""
            return True, "section"
        return False, ""

    for line in body_lines:
        stripped = line.strip()
        if not stripped:
            if article_buffer:
                article_buffer.append(" ")
            continue

        if stripped == "序 言":
            preamble_active = True
            continue

        if preamble_active:
            ch_m = CHAPTER_PATTERN.match(stripped)
            if ch_m:
                preamble_active = False
                current_chapter = {
                    "number": cn_to_int(ch_m.group(1)),
                    "title": ch_m.group(2).strip(),
                }
            else:
                preamble_parts.append(stripped)
            continue

        art_m = ARTICLE_PATTERN.match(stripped)
        is_heading, heading_type = _is_likely_heading(stripped)

        if is_heading:
            _flush_article()
            if heading_type == "chapter":
                _flush_chapter()
                ch_m = CHAPTER_PATTERN.match(stripped)
                if ch_m is None:
                    continue
                current_chapter = {
                    "number": cn_to_int(ch_m.group(1)),
                    "title": ch_m.group(2).strip(),
                }
            else:
                _flush_section()
                sec_m = SECTION_PATTERN.match(stripped)
                if sec_m is None:
                    continue
                current_section = {
                    "number": cn_to_int(sec_m.group(1)),
                    "title": sec_m.group(2).strip(),
                }
            continue

        if art_m:
            art_num = cn_to_int(art_m.group(1))
            if article_number is not None and art_num <= article_number:
                article_buffer.append(stripped)
                continue
            _flush_article()
            article_number = art_num
            first_part = art_m.group(2)
            if first_part:
                article_buffer.append(first_part)
            continue

        if article_number is not None:
            article_buffer.append(stripped)
            continue

    _flush_article()
    _flush_chapter()

    if current_articles and current_chapter is None:
        top_level_articles = list(current_articles)

    result: dict = {
        "law_name": law_name,
        "preamble": "".join(preamble_parts).strip() if preamble_parts else None,
    }

    if chapters:
        result["chapters"] = chapters
    elif top_level_articles:
        result["articles"] = top_level_articles

    return result


def write_structured_law(
    parsed: dict,
    output_dir: Path,
    law_name: str | None = None,
) -> Path:
    """Write a parsed multi-level law structure to a readable text file.

    The output format preserves chapter/section/article hierarchy:
        ===================================
        中华人民共和国XX法
        ===================================

        序  言
        (preamble text)

        第一章 总  则

        第一条  (content)

        第二章 ...

    Returns the output file path.
    """
    name = law_name or parsed.get("law_name", "unknown_law")
    safe_name = re.sub(r"[^\w\u4e00-\u9fff\-]", "_", name)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_name}.txt"

    lines: list[str] = []
    lines.extend(("=" * 60, name, "=" * 60, ""))

    preamble = parsed.get("preamble")
    if preamble:
        lines.extend(("序  言", "", preamble, ""))

    for chapter in parsed.get("chapters", []):
        ch_num = chapter["number"]
        ch_title = chapter["title"]
        lines.extend((f"第{_format_num(ch_num)}章  {ch_title}", ""))

        for section in chapter.get("sections", []):
            sec_num = section["number"]
            sec_title = section["title"]
            lines.extend((f"    第{_format_num(sec_num)}节  {sec_title}", ""))

            for art in section.get("articles", []):
                lines.extend((f"    第{_format_num(art['number'])}条  {art['content']}", ""))

        for art in chapter.get("articles", []):
            if not chapter.get("sections"):
                lines.extend((f"    第{_format_num(art['number'])}条  {art['content']}", ""))

    for art in parsed.get("articles", []):
        lines.extend((f"第{_format_num(art['number'])}条  {art['content']}", ""))

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _format_num(n: int) -> str:
    """Format a number using Chinese numerals for single-level use."""
    digits = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    if n <= 10:
        return digits[n]
    if n < 20:
        return f"十{digits[n - 10]}"
    if n < 100:
        tens = n // 10
        ones = n % 10
        if ones == 0:
            return f"{digits[tens]}十"
        return f"{digits[tens]}十{digits[ones]}"
    if n < 1000:
        hundreds = n // 100
        rest = n % 100
        result = f"{digits[hundreds]}百"
        if rest == 0:
            return result
        if rest <= 10:
            return f"{result}零{digits[rest]}"
        if rest < 20:
            return f"{result}一十{digits[rest - 10]}" if rest > 10 else f"{result}一十"
        tens = rest // 10
        ones = rest % 10
        if ones == 0:
            return f"{result}{digits[tens]}十"
        return f"{result}{digits[tens]}十{digits[ones]}"
    return str(n)

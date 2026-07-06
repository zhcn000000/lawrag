import re

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
    # 检测是否是宪法格式 (开头有标题信息和目录)
    if content.strip().startswith("中华人民共和国宪法"):
        return parse_format_a(content)

    result = parse_format_b(content)
    if result and law_name_override:
        return [(law_name_override, num, content) for _, num, content in result]
    return result

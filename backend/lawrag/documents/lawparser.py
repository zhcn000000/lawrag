import re

from anyio import Path as AsyncPath

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


CHAPTER_PATTERN = re.compile(r"^第([零一二三四五六七八九十百千]+)章\s*(.+)$")
SECTION_PATTERN = re.compile(r"^第([零一二三四五六七八九十百千]+)节\s*(.+)$")
ARTICLE_PATTERN = re.compile(r"^第([零一二三四五六七八九十百千]+)条\s*(.*)$")
ARTICLE_HEADING_PAT = re.compile(r"^第[零一二三四五六七八九十百千]+条\s+")
PART_PATTERN = re.compile(r"^第([零一二三四五六七八九十百千]+)编\s*(.+)$")
SUBPART_PATTERN = re.compile(r"^第([零一二三四五六七八九十百千]+)分编\s*(.+)$")

STRUCT_RULE_PATTERN = re.compile(r"^=+$")

# 节点类型 -> path 段前缀, 用于构造稳定的物化路径 (materialized path) 作为去重键
_PATH_SEGMENT = {
    "part": "b",
    "subpart": "sb",
    "chapter": "c",
    "section": "s",
    "article": "a",
    "preamble": "pre",
}


def _norm(s: str) -> str:
    """去除半角/全角空格, 用于比对无实义分隔空格的标题 (如 '序　言' / '目　录')。"""
    return s.replace(" ", "").replace("\u3000", "")


def _is_preamble_marker(line: str) -> bool:
    return _norm(line) == "序言"


def has_parsed_content(parsed: dict) -> bool:
    """``parse_multi_level`` 结果是否含可写出的实质内容 (编/章/条/序言之一)。"""
    return bool(
        parsed and (parsed.get("parts") or parsed.get("chapters") or parsed.get("articles") or parsed.get("preamble"))
    )


def _assign_paths(nodes: list[dict]) -> None:
    """为每个节点计算稳定的物化路径 ``path`` (同一部法律内唯一, 作为去重键)。"""
    for i, node in enumerate(nodes):
        parent = node["parent"]
        seg_prefix = _PATH_SEGMENT.get(node["node_type"], node["node_type"])
        # number 缺失 (如序言) 时退化用 order 下标
        seg = f"{seg_prefix}{node['number']}" if node.get("number") is not None else f"{seg_prefix}{i}"
        node["path"] = seg if parent is None else f"{nodes[parent]['path']}/{seg}"


def parse_structured_law(content: str, law_name: str) -> list[dict]:
    """解析 ``write_structured_law`` 生成的多级结构化法律文本, 返回树状节点列表.

    每个节点为 dict, ``parent`` 为其父节点在返回列表中的下标 (根节点为 None),
    ``path`` 为同一部法律内唯一的物化路径 (用于去重)::

        {
            "node_type": str,
            "number": int | None,
            "title": str | None,
            "content": str | None,
            "parent": int | None,
            "path": str,
        }

    列表首个元素恒为 node_type="law" 的根节点; 其后按原文顺序为
    preamble / part(编) / subpart(分编) / chapter(章) / section(节) / article(条)。
    层级关系: 编 → 分编 → 章 → 节 → 条; 缺失的层级会被跳过, 条挂在最近的祖先下。
    """
    nodes: list[dict] = [
        {"node_type": "law", "number": None, "title": law_name, "content": None, "parent": None},
    ]
    root = 0
    part: int | None = None
    subpart: int | None = None
    chapter: int | None = None
    section: int | None = None

    preamble_active = False
    preamble_buf: list[str] = []

    def flush_preamble() -> None:
        nonlocal preamble_active
        text = "".join(preamble_buf).strip()
        if text:
            nodes.append(
                {"node_type": "preamble", "number": None, "title": None, "content": text, "parent": root},
            )
        preamble_buf.clear()
        preamble_active = False

    def nearest(*candidates: int | None) -> int:
        for c in candidates:
            if c is not None:
                return c
        return root

    for raw in content.splitlines():
        line = raw.strip()
        if not line or STRUCT_RULE_PATTERN.match(line):
            continue

        if _is_preamble_marker(line):
            preamble_active = True
            continue

        subpart_match = SUBPART_PATTERN.match(line)
        part_match = None if subpart_match else PART_PATTERN.match(line)
        chapter_match = CHAPTER_PATTERN.match(line)
        section_match = SECTION_PATTERN.match(line)
        article_match = ARTICLE_PATTERN.match(line)

        if part_match:
            flush_preamble()
            part, subpart, chapter, section = len(nodes), None, None, None
            nodes.append({
                "node_type": "part",
                "number": cn_to_int(part_match.group(1)),
                "title": part_match.group(2).strip(),
                "content": None,
                "parent": root,
            })
            continue

        if subpart_match:
            flush_preamble()
            subpart, chapter, section = len(nodes), None, None
            nodes.append({
                "node_type": "subpart",
                "number": cn_to_int(subpart_match.group(1)),
                "title": subpart_match.group(2).strip(),
                "content": None,
                "parent": nearest(part, root),
            })
            continue

        if chapter_match:
            flush_preamble()
            chapter, section = len(nodes), None
            nodes.append({
                "node_type": "chapter",
                "number": cn_to_int(chapter_match.group(1)),
                "title": chapter_match.group(2).strip(),
                "content": None,
                "parent": nearest(subpart, part, root),
            })
            continue

        if section_match:
            flush_preamble()
            section = len(nodes)
            nodes.append({
                "node_type": "section",
                "number": cn_to_int(section_match.group(1)),
                "title": section_match.group(2).strip(),
                "content": None,
                "parent": nearest(chapter, subpart, part, root),
            })
            continue

        if article_match:
            flush_preamble()
            nodes.append({
                "node_type": "article",
                "number": cn_to_int(article_match.group(1)),
                "title": None,
                "content": article_match.group(2).strip(),
                "parent": nearest(section, chapter, subpart, part, root),
            })
            continue

        # 非标题正文: 序言累积, 或作为上一条法条的续行
        if preamble_active:
            preamble_buf.append(line)
        elif nodes[-1]["node_type"] == "article":
            nodes[-1]["content"] = (nodes[-1]["content"] or "") + line

    flush_preamble()
    _assign_paths(nodes)
    return nodes


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

    parts: list[dict] = []
    chapters: list[dict] = []
    current_part: dict | None = None
    current_subpart: dict | None = None
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

    def _chapter_bucket() -> list[dict]:
        """章应归入的容器: 分编 > 编 > 顶层 chapters。"""
        if current_subpart is not None:
            return current_subpart.setdefault("chapters", [])
        if current_part is not None:
            return current_part.setdefault("chapters", [])
        return chapters

    def _flush_chapter() -> None:
        nonlocal current_chapter
        _flush_section()
        if current_chapter is not None:
            current_chapter["articles"] = list(current_articles) if current_articles else []
            current_articles.clear()
            _chapter_bucket().append(current_chapter)
        current_chapter = None

    def _flush_subpart() -> None:
        nonlocal current_subpart
        _flush_chapter()
        if current_subpart is not None:
            if current_part is not None:
                current_part.setdefault("subparts", []).append(current_subpart)
            current_subpart = None

    def _flush_part() -> None:
        nonlocal current_part
        _flush_subpart()
        if current_part is not None:
            parts.append(current_part)
        current_part = None

    def _is_heading(stripped: str) -> bool:
        return bool(
            PART_PATTERN.match(stripped)
            or SUBPART_PATTERN.match(stripped)
            or CHAPTER_PATTERN.match(stripped)
            or SECTION_PATTERN.match(stripped)
            or _is_preamble_marker(stripped),
        )

    # Detect and skip table of contents (raw markitdown 常把目录整段列在正文前, 会与正文重复)
    toc_end = -1
    for i, line in enumerate(lines):
        if _norm(line.strip()) == "目录":
            toc_end = i
            break

    if toc_end >= 0:
        # 正文起点: 优先取第一条法条之前最后一个 "第X编" (编级正文的开头), 避免落进目录内层
        first_article_idx = next(
            (i for i in range(toc_end + 1, len(lines)) if ARTICLE_HEADING_PAT.match(lines[i].strip())),
            len(lines),
        )
        part_idx = [i for i in range(toc_end + 1, first_article_idx) if PART_PATTERN.match(lines[i].strip())]
        if part_idx:
            body_start = max(part_idx)
        else:
            # 无编: 沿用"目录后第一个非标题行前的最后一个标题行"启发式 (兼容宪法序言)
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
    _line_split_pattern = re.compile(r"(第[零一二三四五六七八九十百千]+(?:条|章))\s+")

    # Split lines that contain multiple articles/chapters on the same line
    # Only splits when the first 第X条/第X章 is at line start (preceded only by whitespace).
    # Cross-references like "依据本法第十一条规定" won't match because they're not at position 0,
    # so the whole line stays intact — the main loop's N+1 increment check handles the rest.
    def _split_multi_articles(lines_input: list[str]) -> list[str]:
        result: list[str] = []
        for line in lines_input:
            stripped = line.strip()
            if not stripped:
                result.append("")
                continue

            matches = list(_line_split_pattern.finditer(stripped))
            if not matches:
                result.append(stripped)
                continue

            # Only split when the first pattern match is at line start
            if matches[0].start() != 0:
                result.append(stripped)
                continue

            for idx_match, match in enumerate(matches):
                start = match.start()
                next_start = matches[idx_match + 1].start() if idx_match + 1 < len(matches) else len(stripped)
                result.append(stripped[start:next_start])
        return result

    body_lines = _split_multi_articles(body_lines)

    def _is_likely_heading(stripped: str) -> tuple[str, int, str] | None:
        """将以 第X编/分编/章/节 开头的真标题解析为 ``(kind, number, title)``; 正文引用返回 None。"""
        for pattern, kind in (
            (SUBPART_PATTERN, "subpart"),
            (PART_PATTERN, "part"),
            (CHAPTER_PATTERN, "chapter"),
            (SECTION_PATTERN, "section"),
        ):
            m = pattern.match(stripped)
            if m:
                title = m.group(2).strip()
                if not title or title[0] in "的第之中。，、；":
                    return None
                return kind, cn_to_int(m.group(1)), title
        return None

    for line in body_lines:
        stripped = line.strip()
        if not stripped:
            if article_buffer:
                article_buffer.append(" ")
            continue

        if _is_preamble_marker(stripped):
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
        heading = _is_likely_heading(stripped)

        if heading is not None:
            kind, number, title = heading
            _flush_article()
            if kind == "part":
                _flush_part()
                current_part = {"number": number, "title": title}
            elif kind == "subpart":
                _flush_subpart()
                current_subpart = {"number": number, "title": title}
            elif kind == "chapter":
                _flush_chapter()
                current_chapter = {"number": number, "title": title}
            else:
                _flush_section()
                current_section = {"number": number, "title": title}
            continue

        if art_m:
            art_num = cn_to_int(art_m.group(1))
            has_space_after = bool(ARTICLE_HEADING_PAT.match(line))

            if article_number is not None:
                # Inside active article: only accept immediately next number + heading spacing
                if art_num == article_number + 1 and has_space_after:
                    _flush_article()
                    article_number = art_num
                    first_part = art_m.group(2)
                    if first_part:
                        article_buffer.append(first_part)
                else:
                    article_buffer.append(stripped)
                continue

            # No active article yet: use spacing heuristic to guard against cross-refs
            if has_space_after:
                article_number = art_num
                first_part = art_m.group(2)
                if first_part:
                    article_buffer.append(first_part)
            continue

        if article_number is not None:
            article_buffer.append(stripped)
            continue

    _flush_article()
    _flush_part()
    _flush_chapter()

    if current_articles and current_chapter is None:
        top_level_articles = list(current_articles)

    result: dict = {
        "law_name": law_name,
        "preamble": "".join(preamble_parts).strip() if preamble_parts else None,
    }

    if parts:
        result["parts"] = parts
    if chapters:
        result["chapters"] = chapters
    if not parts and not chapters and top_level_articles:
        result["articles"] = top_level_articles

    return result


async def write_structured_law(
    parsed: dict,
    output_dir: AsyncPath,
    law_name: str | None = None,
) -> AsyncPath:
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
    await output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_name}.txt"

    lines: list[str] = []
    lines.extend(("=" * 60, name, "=" * 60, ""))

    preamble = parsed.get("preamble")
    if preamble:
        lines.extend(("序  言", "", preamble, ""))

    def _write_chapter(chapter: dict) -> None:
        lines.extend((f"第{_format_num(chapter['number'])}章  {chapter['title']}", ""))
        for section in chapter.get("sections", []):
            lines.extend((f"    第{_format_num(section['number'])}节  {section['title']}", ""))
            for art in section.get("articles", []):
                lines.extend((f"    第{_format_num(art['number'])}条  {art['content']}", ""))
        if not chapter.get("sections"):
            for art in chapter.get("articles", []):
                lines.extend((f"    第{_format_num(art['number'])}条  {art['content']}", ""))

    for part in parsed.get("parts", []):
        lines.extend((f"第{_format_num(part['number'])}编  {part['title']}", ""))
        for subpart in part.get("subparts", []):
            lines.extend((f"第{_format_num(subpart['number'])}分编  {subpart['title']}", ""))
            for chapter in subpart.get("chapters", []):
                _write_chapter(chapter)
        for chapter in part.get("chapters", []):
            _write_chapter(chapter)

    for chapter in parsed.get("chapters", []):
        _write_chapter(chapter)

    for art in parsed.get("articles", []):
        lines.extend((f"第{_format_num(art['number'])}条  {art['content']}", ""))

    await output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _format_num(n: int) -> str:
    """将整数转为中文数字 (支持 1-9999, 与 ``cn_to_int`` 可逆)。"""
    if n <= 0:
        return "零"
    if n >= 10000:
        return str(n)
    digits = "零一二三四五六七八九"
    units = ["", "十", "百", "千"]
    s = str(n)
    length = len(s)
    result = ""
    pending_zero = False
    for i, ch in enumerate(s):
        d = int(ch)
        pos = length - i - 1
        if d == 0:
            pending_zero = True
            continue
        if pending_zero:
            result += "零"
            pending_zero = False
        result += digits[d] + units[pos]
    # 中文习惯: 10-19 写作 "十X" 而非 "一十X"
    if result.startswith("一十"):
        result = result[1:]
    return result

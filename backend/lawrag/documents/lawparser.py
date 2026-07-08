import re

from cn2an import cn2an


def has_parsed_content(parsed: dict) -> bool:
    """``parse_multi_level`` 结果是否含可写出的实质内容 (编/章/条/序言之一)。"""
    return bool(
        parsed and (parsed.get("parts") or parsed.get("chapters") or parsed.get("articles") or parsed.get("preamble")),
    )


def flatten_hierarchy(parsed: dict, law_name: str) -> list[dict]:
    """将 ``parse_multi_level`` 输出的嵌套 dict 扁平化为带 parent/path 的 node 列表。

    输出格式与原 ``parse_structured_law`` 兼容:
    [{"node_type", "number", "title", "content", "parent", "path"}, ...]
    首个元素恒为 node_type="law" 的根节点。
    """
    nodes: list[dict] = [
        {"node_type": "law", "number": None, "title": law_name, "content": None, "parent": None},
    ]
    root = 0

    def _add(node_type: str, number: int | None, title: str | None, content: str | None, parent: int) -> int:
        idx = len(nodes)
        nodes.append({"node_type": node_type, "number": number, "title": title, "content": content, "parent": parent})
        return idx

    def _walk_chapter(ch: dict, parent: int) -> None:
        ch_idx = _add("chapter", ch["number"], ch["title"], None, parent)
        for sec in ch.get("sections", []):
            sec_idx = _add("section", sec["number"], sec["title"], None, ch_idx)
            for art in sec.get("articles", []):
                _add("article", art["number"], None, art["content"], sec_idx)
        for art in ch.get("articles", []):
            _add("article", art["number"], None, art["content"], ch_idx)

    preamble = parsed.get("preamble")
    if preamble:
        _add("preamble", None, None, preamble, root)

    for part in parsed.get("parts", []):
        p_idx = _add("part", part["number"], part["title"], None, root)
        for sub in part.get("subparts", []):
            s_idx = _add("subpart", sub["number"], sub["title"], None, p_idx)
            for ch in sub.get("chapters", []):
                _walk_chapter(ch, s_idx)
        for ch in part.get("chapters", []):
            _walk_chapter(ch, p_idx)

    for ch in parsed.get("chapters", []):
        _walk_chapter(ch, root)

    for art in parsed.get("articles", []):
        _add("article", art["number"], None, art["content"], root)

    LawParser._assign_paths(nodes)
    return nodes


class LawParser:
    """多级法律文本解析器 (编/分编/章/节/条)。

    用法::

        parsed = LawParser().parse(content)
    """

    _CHAPTER_PATTERN = re.compile(r"^第([零一二三四五六七八九十百千]+)章\s*(.+)$")
    _SECTION_PATTERN = re.compile(r"^第([零一二三四五六七八九十百千]+)节\s*(.+)$")
    _ARTICLE_PATTERN = re.compile(r"^第([零一二三四五六七八九十百千]+)条\s*(.*)$")
    _ARTICLE_HEADING_PAT = re.compile(r"^第[零一二三四五六七八九十百千]+条\s+")
    _PART_PATTERN = re.compile(r"^第([零一二三四五六七八九十百千]+)编\s*(.+)$")
    _SUBPART_PATTERN = re.compile(r"^第([零一二三四五六七八九十百千]+)分编\s*(.+)$")
    _LINE_SPLIT_PATTERN = re.compile(r"(第[零一二三四五六七八九十百千]+(?:条|章))\s+")

    # 节点类型 -> path 段前缀, 用于构造稳定的物化路径 (materialized path) 作为去重键
    _PATH_SEGMENT = {
        "part": "b",
        "subpart": "sb",
        "chapter": "c",
        "section": "s",
        "article": "a",
        "preamble": "pre",
    }

    def __init__(self) -> None:
        self.preamble_parts: list[str] = []
        self.preamble_active = False

        self.parts: list[dict] = []
        self.chapters: list[dict] = []
        self.current_part: dict | None = None
        self.current_subpart: dict | None = None
        self.current_chapter: dict | None = None
        self.current_section: dict | None = None
        self.current_articles: list[dict] = []
        self.top_level_articles: list[dict] = []
        self.law_name = ""

        self.article_buffer: list[str] = []
        self.article_number: int | None = None

    @staticmethod
    def _norm(s: str) -> str:
        """去除半角/全角空格, 用于比对无实义分隔空格的标题 (如 '序　言' / '目　录')。"""
        return s.replace(" ", "").replace("\u3000", "")

    @staticmethod
    def _is_preamble_marker(line: str) -> bool:
        return LawParser._norm(line) == "序言"

    @classmethod
    def _is_heading(cls, stripped: str) -> bool:
        return bool(
            cls._PART_PATTERN.match(stripped)
            or cls._SUBPART_PATTERN.match(stripped)
            or cls._CHAPTER_PATTERN.match(stripped)
            or cls._SECTION_PATTERN.match(stripped)
            or cls._is_preamble_marker(stripped),
        )

    @classmethod
    def _is_likely_heading(cls, stripped: str) -> tuple[str, int, str] | None:
        """将以 第X编/分编/章/节 开头的真标题解析为 (kind, number, title); 正文引用返回 None。"""
        for pattern, kind in (
            (cls._SUBPART_PATTERN, "subpart"),
            (cls._PART_PATTERN, "part"),
            (cls._CHAPTER_PATTERN, "chapter"),
            (cls._SECTION_PATTERN, "section"),
        ):
            m = pattern.match(stripped)
            if m:
                title = m.group(2).strip()
                if not title or title[0] in "的第之中。，、；":
                    return None
                return kind, int(cn2an(m.group(1), "strict")), title
        return None

    @classmethod
    def _assign_paths(cls, nodes: list[dict]) -> None:
        """为每个节点计算稳定的物化路径 ``path`` (同一部法律内唯一, 作为去重键)。"""
        for i, node in enumerate(nodes):
            parent = node["parent"]
            seg_prefix = cls._PATH_SEGMENT.get(node["node_type"], node["node_type"])
            seg = f"{seg_prefix}{node['number']}" if node.get("number") is not None else f"{seg_prefix}{i}"
            node["path"] = seg if parent is None else f"{nodes[parent]['path']}/{seg}"

    @classmethod
    def _detect_law_name(cls, lines: list[str]) -> str:
        """从前 10 行检测法律名称。"""
        for line in lines[:10]:
            stripped = line.strip()
            if stripped.startswith("中华人民共和国") and "法" in stripped and not stripped.startswith("第"):
                return stripped.split(" ")[0].split("\t")[0]
        return ""

    @classmethod
    def _split_multi_articles(cls, lines_input: list[str]) -> list[str]:
        """拆分同一行内连续多个 第X条/第X章, 只在行首命中时拆分, 避免拆分正文引用。"""
        result: list[str] = []
        for line in lines_input:
            stripped = line.strip()
            if not stripped:
                result.append("")
                continue
            matches = list(cls._LINE_SPLIT_PATTERN.finditer(stripped))
            if not matches:
                result.append(stripped)
                continue
            if matches[0].start() != 0:
                result.append(stripped)
                continue
            for idx_match, match in enumerate(matches):
                start = match.start()
                next_start = matches[idx_match + 1].start() if idx_match + 1 < len(matches) else len(stripped)
                result.append(stripped[start:next_start])
        return result

    @classmethod
    def _detect_and_skip_toc(cls, lines: list[str]) -> list[str]:
        """检测并跳过目录部分, 返回正文行列表。

        支持三种情形:
        1. 显式"目录"标记
        2. 章/节标题在第一条前重复出现 (隐式 TOC)
        3. 无目录
        """
        toc_end = -1
        for i, line in enumerate(lines):
            if cls._norm(line.strip()) == "目录":
                toc_end = i
                break

        if toc_end >= 0:
            first_article_idx = next(
                (i for i in range(toc_end + 1, len(lines)) if cls._ARTICLE_HEADING_PAT.match(lines[i].strip())),
                len(lines),
            )
            part_idx = [i for i in range(toc_end + 1, first_article_idx) if cls._PART_PATTERN.match(lines[i].strip())]
            if part_idx:
                body_start = max(part_idx)
            else:
                body_start = toc_end + 1
                for j in range(toc_end + 1, len(lines)):
                    stripped = lines[j].strip()
                    if not stripped:
                        continue
                    if not cls._is_heading(stripped):
                        for k in range(j - 1, toc_end, -1):
                            if lines[k].strip():
                                body_start = k
                                break
                        break
            return lines[body_start:]

        first_article_idx = next(
            (i for i, line in enumerate(lines) if cls._ARTICLE_HEADING_PAT.match(line.strip())),
            len(lines),
        )
        heading_key: set[tuple[str, int, str]] = set()
        dup_start = -1
        for i in range(first_article_idx):
            stripped = lines[i].strip()
            key: tuple[str, int, str] | None = None
            for pat, kind in (
                (cls._CHAPTER_PATTERN, "chapter"),
                (cls._SECTION_PATTERN, "section"),
                (cls._PART_PATTERN, "part"),
                (cls._SUBPART_PATTERN, "subpart"),
            ):
                m = pat.match(stripped)
                if m:
                    title = m.group(2).strip()
                    if not title or title[0] in "的第之中。，、；":
                        break  # skip: the pattern matched but the title starts with meaningless punctuation
                    key = (kind, int(cn2an(m.group(1), "strict")), title)
                    break
            if key is not None:
                if key in heading_key:
                    dup_start = i
                else:
                    heading_key.add(key)
        if dup_start >= 0:
            body_start = dup_start
            for k in range(dup_start - 1, -1, -1):
                if lines[k].strip():
                    body_start = k
                    break
            return lines[body_start:]
        return lines

    def flush_article(self) -> None:
        if self.article_number is not None and self.article_buffer:
            content = "".join(self.article_buffer).strip()
            self.current_articles.append({"number": self.article_number, "content": content})
        self.article_buffer = []
        self.article_number = None

    def flush_section(self) -> None:
        self.flush_article()
        if self.current_section is not None:
            self.current_section["articles"] = list(self.current_articles)
            self.current_articles.clear()
            if self.current_chapter is not None:
                self.current_chapter.setdefault("sections", []).append(self.current_section)
            self.current_section = None

    def chapter_bucket(self) -> list[dict]:
        if self.current_subpart is not None:
            return self.current_subpart.setdefault("chapters", [])
        if self.current_part is not None:
            return self.current_part.setdefault("chapters", [])
        return self.chapters

    def flush_chapter(self) -> None:
        self.flush_section()
        if self.current_chapter is not None:
            self.current_chapter["articles"] = list(self.current_articles) if self.current_articles else []
            self.current_articles.clear()
            self.chapter_bucket().append(self.current_chapter)
        self.current_chapter = None

    def flush_subpart(self) -> None:
        self.flush_chapter()
        if self.current_subpart is not None:
            if self.current_part is not None:
                self.current_part.setdefault("subparts", []).append(self.current_subpart)
            self.current_subpart = None

    def flush_part(self) -> None:
        self.flush_subpart()
        if self.current_part is not None:
            self.parts.append(self.current_part)
        self.current_part = None

    def flush_all(self) -> None:
        self.flush_article()
        self.flush_part()
        self.flush_chapter()

    def process_line(self, stripped: str, line: str) -> None:
        if not stripped:
            if self.article_buffer:
                self.article_buffer.append(" ")
            return

        if self._is_preamble_marker(stripped):
            self.preamble_active = True
            return

        if self.preamble_active:
            ch_m = self._CHAPTER_PATTERN.match(stripped)
            if ch_m:
                self.preamble_active = False
                self.current_chapter = {
                    "number": int(cn2an(ch_m.group(1), "strict")),
                    "title": ch_m.group(2).strip(),
                }
            else:
                self.preamble_parts.append(stripped)
            return

        art_m = self._ARTICLE_PATTERN.match(stripped)
        heading = self._is_likely_heading(stripped)

        if heading is not None:
            kind, number, title = heading
            self.flush_article()
            if kind == "part":
                self.flush_part()
                self.current_part = {"number": number, "title": title}
            elif kind == "subpart":
                self.flush_subpart()
                self.current_subpart = {"number": number, "title": title}
            elif kind == "chapter":
                self.flush_chapter()
                self.current_chapter = {"number": number, "title": title}
            else:
                self.flush_section()
                self.current_section = {"number": number, "title": title}
            return

        if art_m:
            art_num = int(cn2an(art_m.group(1), "strict"))
            has_space_after = bool(self._ARTICLE_HEADING_PAT.match(line))

            if self.article_number is not None:
                if art_num == self.article_number + 1 and has_space_after:
                    self.flush_article()
                    self.article_number = art_num
                    first_part = art_m.group(2)
                    if first_part:
                        self.article_buffer.append(first_part)
                else:
                    self.article_buffer.append(stripped)
                return

            if has_space_after:
                self.article_number = art_num
                first_part = art_m.group(2)
                if first_part:
                    self.article_buffer.append(first_part)
            return

        if self.article_number is not None:
            self.article_buffer.append(stripped)

    def build_result(self) -> dict:
        if self.current_articles and self.current_chapter is None:
            self.top_level_articles = list(self.current_articles)

        result: dict = {
            "law_name": self.law_name,
            "preamble": "".join(self.preamble_parts).strip() if self.preamble_parts else None,
        }
        if self.parts:
            result["parts"] = self.parts
        if self.chapters:
            result["chapters"] = self.chapters
        if not self.parts and not self.chapters and self.top_level_articles:
            result["articles"] = self.top_level_articles
        return result

    def parse(self, content: str) -> dict:
        """解析完整法律文本, 返回层级 dict。"""
        lines = content.splitlines()
        self.law_name = self._detect_law_name(lines)

        body_lines = self._detect_and_skip_toc(lines)
        body_lines = self._split_multi_articles(body_lines)

        for line in body_lines:
            self.process_line(line.strip(), line)

        self.flush_all()
        return self.build_result()


def parse_multi_level(content: str) -> dict:
    """Parse a full law text preserving multi-level chapter/section/article hierarchy.

    Convenience wrapper around ``LawParser().parse(content)``.
    """
    return LawParser().parse(content)

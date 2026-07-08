import pytest

from lawrag.documents.lawparser import cn_to_int, has_parsed_content, parse_multi_level, parse_structured_law

STRUCTURED_LAW = "\n".join([
    "=" * 60,
    "中华人民共和国测试法",
    "=" * 60,
    "",
    "第一编  总则",
    "",
    "第一章  基本规定",
    "",
    "    第一条  为了保护测试主体的合法权益，根据宪法，制定本法。",
    "",
    "    第二条  测试法调整测试关系。",
    "",
    "第二编  权利",
    "",
    "第一分编  人身权利",
    "",
    "第二章  权利总则",
    "",
    "    第一节  一般规定",
    "",
    "    第三条  测试主体依法享有测试权利。",
    "",
    "    第二节  特别规定",
    "",
    "    第四条  测试活动应当遵循自愿原则。",
    "",
])

TOP_LEVEL_LAW = "\n".join([
    "=" * 60,
    "中华人民共和国简法",
    "=" * 60,
    "",
    "第一条  简法第一条。",
    "",
    "第二条  简法第二条。",
    "",
])


@pytest.mark.parametrize(
    ("cn", "expected"),
    [
        ("一", 1),
        ("二", 2),
        ("十", 10),
        ("十一", 11),
        ("二十", 20),
        ("二十五", 25),
        ("一百", 100),
        ("一百二十三", 123),
        ("一千二百三十四", 1234),
    ],
)
def test_cn_to_int(cn: str, expected: int) -> None:
    assert cn_to_int(cn) == expected


def test_parse_structured_root_and_counts() -> None:
    nodes = parse_structured_law(STRUCTURED_LAW, law_name="中华人民共和国测试法")
    assert nodes[0]["node_type"] == "law"
    assert nodes[0]["parent"] is None
    assert nodes[0]["title"] == "中华人民共和国测试法"

    types = [n["node_type"] for n in nodes]
    assert types.count("part") == 2
    assert types.count("subpart") == 1
    assert types.count("chapter") == 2
    assert types.count("section") == 2
    assert types.count("article") == 4


def test_parse_structured_paths_unique() -> None:
    nodes = parse_structured_law(STRUCTURED_LAW, law_name="中华人民共和国测试法")
    paths = [n["path"] for n in nodes]
    assert len(paths) == len(set(paths))


def test_parse_structured_hierarchy() -> None:
    nodes = parse_structured_law(STRUCTURED_LAW, law_name="中华人民共和国测试法")

    # 第三条 → 第一节 → 第二章 → 第一分编 → 第二编 → law
    art3 = next(n for n in nodes if n["node_type"] == "article" and n["number"] == 3)
    section = nodes[art3["parent"]]
    assert section["node_type"] == "section"
    assert section["title"] == "一般规定"
    chapter = nodes[section["parent"]]
    assert chapter["node_type"] == "chapter"
    assert chapter["title"] == "权利总则"
    subpart = nodes[chapter["parent"]]
    assert subpart["node_type"] == "subpart"
    assert subpart["title"] == "人身权利"
    part = nodes[subpart["parent"]]
    assert part["node_type"] == "part"
    assert part["title"] == "权利"

    # 第一条 → 第一章 → 第一编 (无分编/节)
    art1 = next(n for n in nodes if n["node_type"] == "article" and n["number"] == 1)
    chapter1 = nodes[art1["parent"]]
    assert chapter1["node_type"] == "chapter"
    assert chapter1["title"] == "基本规定"
    assert nodes[chapter1["parent"]]["node_type"] == "part"
    assert nodes[chapter1["parent"]]["title"] == "总则"


def test_parse_structured_top_level_articles() -> None:
    nodes = parse_structured_law(TOP_LEVEL_LAW, law_name="中华人民共和国简法")
    articles = [n for n in nodes if n["node_type"] == "article"]
    assert len(articles) == 2
    # 无编/章时法条直接挂在根节点下
    for art in articles:
        assert nodes[art["parent"]]["node_type"] == "law"


# ── parse_multi_level tests ──────────────────────────────────────────


def test_parse_multi_simple() -> None:
    content = "中华人民共和国测试法\n第一章  总则\n第一条  第一条内容。\n第二条  第二条内容。\n"
    parsed = parse_multi_level(content)
    assert parsed["law_name"] == "中华人民共和国测试法"
    assert parsed["chapters"][0]["articles"][0]["number"] == 1


def test_parse_multi_backward_cross_ref() -> None:
    """引用前文：第117条中引用第11条 → 不应拆为新条目"""
    content = (
        "中华人民共和国测试法\n"
        "第一百一十七条  违反本法\n"
        "第十一条  第二款规定，追究责任。\n"
        "第一百一十八条  下一条内容。\n"
    )
    parsed = parse_multi_level(content)
    arts = parsed["articles"]
    assert len(arts) == 2
    assert arts[0]["number"] == 117
    assert "第十一条" in arts[0]["content"]
    assert arts[1]["number"] == 118


def test_parse_multi_forward_cross_ref() -> None:
    """引用后文(条号非N+1)：第44条中引用第56条 → 不应拆为新条目"""
    content = (
        "中华人民共和国测试法\n"
        "第一章  分则\n"
        "第四十四条  参照第五十六条规定执行。\n"
        "第四十五条  下一条。\n"
        "第二章  附则\n"
        "第五十六条  第五十六条正文。\n"
    )
    parsed = parse_multi_level(content)
    ch1 = parsed["chapters"][0]["articles"]
    assert ch1[0]["number"] == 44
    assert "第五十六条" in ch1[0]["content"]
    ch2 = parsed["chapters"][1]["articles"]
    assert ch2[0]["number"] == 56


def test_parse_multi_inline_ref_not_split() -> None:
    """行内引用(条后无空格)不被_split_multi_articles拆分"""
    content = "中华人民共和国测试法\n第一百一十七条  违反本法第十一条第二款规定，追究责任。\n第一百一十八条  下一条。\n"
    parsed = parse_multi_level(content)
    arts = parsed["articles"]
    assert len(arts) == 2
    assert "第十一条第二款" in arts[0]["content"]


def test_parse_multi_content_starts_with_ref() -> None:
    """法条正文以引用条目开头时(如'第一条  第一条内容')不误判"""
    content = (
        "中华人民共和国测试法\n第一条  第一条内容参照本法第三条规定。\n第二条  第二条内容。\n第三条  第三条正文。\n"
    )
    parsed = parse_multi_level(content)
    arts = parsed["articles"]
    assert len(arts) == 3
    assert arts[0]["number"] == 1
    assert "第三条" in arts[0]["content"]


def test_parse_multi_empty() -> None:
    assert parse_multi_level("") == {"law_name": "", "preamble": None}


def test_parse_multi_parts_and_toc() -> None:
    """含目录(编/分编/章)且正文重复目录时: 跳过目录, 仅解析正文, 并还原编/分编层级。"""
    content = "\n".join([
        "中华人民共和国测试法典",
        "目　　录",
        "第一编　总　　则",
        "第一章　基本规定",
        "第二编　物　　权",
        "第一分编　通　　则",
        "第一章　一般规定",
        "第一编　总　　则",  # 正文开始 (重复)
        "第一章　基本规定",
        "第一条　总则第一条。",
        "第二编　物　　权",
        "第一分编　通　　则",
        "第一章　一般规定",
        "第二条　物权第一条。",
    ])
    parsed = parse_multi_level(content)
    assert "parts" in parsed
    assert len(parsed["parts"]) == 2
    p1, p2 = parsed["parts"]
    assert p1["title"] == "总　　则"
    # 第一编 下有直接章, 第一条 在其中
    assert p1["chapters"][0]["articles"][0]["number"] == 1
    # 第二编 下有分编, 分编下有章
    assert p2["subparts"][0]["title"] == "通　　则"
    assert p2["subparts"][0]["chapters"][0]["articles"][0]["number"] == 2


def test_has_parsed_content_parts_only() -> None:
    """仅含 parts 的编结构法律 (如民法典) 应视为解析成功。"""
    content = "\n".join([
        "中华人民共和国测试法典",
        "第一编　总　　则",
        "第一章　基本规定",
        "第一条　总则第一条。",
    ])
    parsed = parse_multi_level(content)
    assert "parts" in parsed
    assert has_parsed_content(parsed) is True


def test_has_parsed_content_empty() -> None:
    assert has_parsed_content(parse_multi_level("")) is False
    assert has_parsed_content({}) is False

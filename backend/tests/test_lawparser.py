import pytest

from lawrag.documents.lawparser import cn_to_int, parse_content, parse_format_a, parse_format_b


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


def test_parse_format_b_single_line() -> None:
    """Test parsing a single standard law article line"""
    line = "《中华人民共和国民法典》第一条规定，为了保护民事主体的合法权益，根据宪法，制定本法。"
    results = parse_format_b(line)
    assert len(results) == 1
    assert results[0][0] == "中华人民共和国民法典"
    assert results[0][1] == 1
    assert results[0][2] == "为了保护民事主体的合法权益，根据宪法，制定本法"


def test_parse_format_b_multiple_lines() -> None:
    """Test parsing multiple standard law article lines"""
    content = "\n".join([
        "《中华人民共和国民法典》第一条规定，为了保护民事主体的合法权益，根据宪法，制定本法。",
        "《中华人民共和国民法典》第二条规定，民法调整平等主体的自然人、法人和非法人组织之间的人身关系和财产关系。",
        "《中华人民共和国民法典》第三条规定，民事主体的人身权利、财产权利以及其他合法权益受法律保护。",
    ])
    results = parse_format_b(content)
    assert len(results) == 3
    assert results[0][1] == 1
    assert results[1][1] == 2
    assert results[2][1] == 3


def test_parse_format_b_empty() -> None:
    assert parse_format_b("") == []
    assert parse_format_b("   \n   \n") == []


def test_parse_content_auto_format_b() -> None:
    """Test auto-detection: format B (standard law)"""
    content = "\n".join([
        "《中华人民共和国反家庭暴力法》第一条规定，为了预防和制止家庭暴力，保护家庭成员的合法权益，制定本法。",
        "《中华人民共和国反家庭暴力法》第二条规定，本法所称家庭暴力，是指家庭成员之间以殴打、捆绑、残害、限制人身自由以及经常性谩骂、恐吓等方式实施的身体、精神等侵害行为。",
    ])
    results = parse_content(content)
    assert len(results) == 2
    assert results[0][0] == "中华人民共和国反家庭暴力法"


def test_parse_format_a_constitution() -> None:
    """Test parsing constitution format (format A)"""
    content = (
        "中华人民共和国宪法（1982年12月4日通过）\n"
        "目 录\n"
        "序 言\n"
        "第一章 总 纲\n"
        "序 言\n"
        "中国是世界上历史最悠久的国家之一。\n"
        "第一章 总 纲\n"
        "第一条 中华人民共和国是工人阶级领导的、以工农联盟为基础的人民民主专政的社会主义国家。\n"
        "第二条 中华人民共和国的一切权力属于人民。\n"
    )
    results = parse_format_a(content)
    assert len(results) >= 2
    law_names = {r[0] for r in results}
    assert "中华人民共和国宪法" in law_names
    article_nums = {r[1] for r in results}
    assert 0 in article_nums  # 序言 = article_number 0
    assert 1 in article_nums
    assert 2 in article_nums


def test_parse_content_auto_format_a() -> None:
    """Test auto-detection: format A (constitution)"""
    content = (
        "中华人民共和国宪法（1982年12月4日通过）\n"
        "目 录\n"
        "第一章 总 纲\n"
        "第一条 中华人民共和国是工人阶级领导的、以工农联盟为基础的人民民主专政的社会主义国家。\n"
    )
    results = parse_content(content)
    assert len(results) >= 1
    assert results[0][0] == "中华人民共和国宪法"

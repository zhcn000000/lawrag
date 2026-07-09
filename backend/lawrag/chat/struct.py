from typing import Literal

from pydantic import BaseModel


class ModelDeps(BaseModel):
    max_result_retries: int = 3
    select_toolset: set[Literal["rag_toolkit", "code_toolkit", "web_toolkit", "subagent_toolkit"]] = {
        "rag_toolkit",
        "code_toolkit",
        "web_toolkit",
        "subagent_toolkit",
    }


class ToolInfo(BaseModel):
    label: str
    description: str
    default_enabled: bool = False
    requires: list[str] = []


class SubagentInfo(BaseModel):
    label: str
    description: str
    instructions: str
    toolkits: list[str] = []


SUBAGENT_REGISTRY: dict[str, SubagentInfo] = {
    "explore_agent": SubagentInfo(
        label="法律知识库探索者",
        description=(
            "该子Agent只使用法律知识库检索工具,适合执行法律条文检索、章节定位、"
            "法规浏览等纯检索型任务。请在需要查询法律条文但主Agent检索工具不足时使用。"
        ),
        instructions=(
            "你是一名专业的中国法律知识库探索者，作为subagent，"
            "你可以根据主agent的指令，通过知识库探索必要的信息，并将信息完善的返回给主agent。"
            "同时返回关键法律的path方便主agent进行后续的法律条文引用。"
        ),
        toolkits=["rag_toolkit"],
    ),
    "general_agent": SubagentInfo(
        label="通用任务处理者",
        description=(
            "该子Agent可以使用代码执行、网络搜索、法律知识库检索等所有工具,"
            "适合执行混合型任务(如网络检索 + 代码计算 + 法律知识库综合分析)。"
            "请在主Agent需要综合多种工具协作完成任务时使用。"
        ),
        instructions=(
            "你是一名专业的中国法律知识库处理者，作为subagent，"
            "你可以根据主agent的指令，各种不同的工具，执行通用任务，并反馈合适的信息给主agent。"
        ),
        toolkits=["code_toolkit", "rag_toolkit", "web_toolkit"],
    ),
}

TOOL_REGISTRY: dict[str, ToolInfo] = {
    "rag_toolkit": ToolInfo(
        label="法律知识库检索",
        description="用于检索法律文档的增强检索工具，支持法律列表、文档搜索、法条目录浏览等。",
        default_enabled=True,
        requires=[],
    ),
    "code_toolkit": ToolInfo(
        label="在容器中执行代码",
        description="用于安全的执行Python代码以进行计算、数据处理等。",
        default_enabled=False,
        requires=[],
    ),
    "web_toolkit": ToolInfo(
        label="搜索网页",
        description="用于实时获取互联网法律法规信息的工具，支持搜索、抓取与内容提取。",
        default_enabled=False,
        requires=[],
    ),
    "subagent_toolkit": ToolInfo(
        label="子Agent协作",
        description="启用后可调用子Agent(explore_agent/general_agent)执行复杂或专业的子任务。",
        default_enabled=False,
        requires=["rag_toolkit"],
    ),
}

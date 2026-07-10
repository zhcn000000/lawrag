from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field
from pydantic_ai import Agent, ModelRetry, RunContext, ToolDefinition
from pydantic_ai.capabilities import Capability

from .code_tools import code_capability
from .rag_tools import rag_capability
from .struct import SUBAGENT_REGISTRY, ModelDeps
from .web_tools import web_capability

subagent_capability: Capability[ModelDeps] = Capability()

SubagentName = Literal["explore_agent", "general_agent"]

TOOLSET_NAME_BY_OBJECT: dict[int, str] = {}


def _map_toolset_name(tools: list[str]) -> list[Capability[ModelDeps]]:
    toolset_map = {
        "rag_toolkit": rag_capability,
        "code_toolkit": code_capability,
        "web_toolkit": web_capability,
        "subagent_toolkit": subagent_capability,
    }
    return [toolset_map[tool] for tool in tools if tool in toolset_map]


@lru_cache(maxsize=len(SUBAGENT_REGISTRY))
def _get_subagent(name: str) -> Agent[ModelDeps, str]:
    spec = SUBAGENT_REGISTRY.get(name)
    if spec is None:
        raise ValueError(f"未知的subagent名称: {name}")
    return Agent(
        deps_type=ModelDeps,
        output_type=str,
        capabilities=_map_toolset_name(spec.toolkits),
        instructions=spec.instructions,
        retries=5,
    )


async def prepare_subagent(ctx: RunContext[ModelDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    if "subagent_toolkit" in ctx.deps.select_toolset:
        return tool_def
    return None


@subagent_capability.instructions
def agent_instructions(ctx: RunContext[ModelDeps]) -> str | None:
    if "subagent_toolkit" not in ctx.deps.select_toolset:
        return None
    text = """当前已经启用了subagent功能，你可以选择调用以下子Agent来执行任务，
除了以下两类排除，子agent可以使用其他所有工具
- 子agent同样无法使用未被用户选中的工具，例如如果你的工具列表中没有code_tools，则子agent也无法访问这个工具，
- 虽然你有这个工具，但是你调用的子agent本身不支持这个工具（体现在简介中），那么子agent也无法访问这个工具
子agent具有其自己的系统提示词以适应符合子agent描述的任务"""
    for agent_name, spec in SUBAGENT_REGISTRY.items():
        text += f"- {agent_name}: {spec.label} - {spec.description}\n"
    return text


@subagent_capability.tool(
    name="subagent",
    description="""调用子Agent来执行任务，子Agent可以使用不同的工具组合来完成任务。
在agent_name中填入子Agent的名称,在task_text中填入要交给子Agent执行的任务文本。""",
    prepare=prepare_subagent,
    include_return_schema=True,
)
async def subagent(
    ctx: RunContext[ModelDeps],
    agent_name: Annotated[SubagentName, Field(description="要调用的子Agent名称")],
    task_text: Annotated[str, Field(description="要交给子Agent执行的任务文本")],
) -> str:
    if agent_name not in SUBAGENT_REGISTRY:
        raise ModelRetry(f"未知的agent名称: {agent_name}，可用agent: {list(SUBAGENT_REGISTRY.keys())}")

    agent = _get_subagent(agent_name)

    result = await agent.run(
        user_prompt=task_text,
        model=ctx.model,
        deps=ctx.deps,
        model_settings=ctx.model_settings,
        output_type=str,
    )

    return result.output

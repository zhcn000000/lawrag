from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field
from pydantic_ai import Agent, FunctionToolset, ModelRetry, RunContext, ToolDefinition

from .code_tools import code_toolset
from .rag_tools import rag_toolset
from .struct import SUBAGENT_REGISTRY, ModelDeps
from .web_tools import web_toolset

subagent_toolset: FunctionToolset[ModelDeps] = FunctionToolset()

SubagentName = Literal["explore_agent", "general_agent"]

TOOLSET_NAME_BY_OBJECT: dict[int, str] = {}


async def prepare_subagent(ctx: RunContext[ModelDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    if "subagent_toolkit" in ctx.deps.select_toolset:
        return tool_def
    return None


def map_toolset_name(tools: list[str]) -> list[FunctionToolset[ModelDeps]]:
    toolset_map = {
        "rag_toolkit": rag_toolset,
        "code_toolkit": code_toolset,
        "web_toolkit": web_toolset,
        "subagent_toolkit": subagent_toolset,
    }
    return [toolset_map[tool] for tool in tools if tool in toolset_map]


@lru_cache(maxsize=len(SUBAGENT_REGISTRY))
def get_subagent(name: str) -> Agent[ModelDeps, str]:
    spec = SUBAGENT_REGISTRY.get(name)
    if spec is None:
        raise ValueError(f"未知的subagent名称: {name}")
    return Agent(
        deps_type=ModelDeps,
        output_type=str,
        toolsets=map_toolset_name(spec.toolkits),
        instructions=spec.instructions,
        retries=5,
    )


def build_description_for_subagent() -> str:
    text = """这是一个子Agent工具，使用该工具可以调用一个子Agent来执行任务，子agent也无法使用未被选中的工具
可用的agent:如下\n"""
    for agent_name, spec in SUBAGENT_REGISTRY.items():
        text += f"- {agent_name}: {spec.label} - {spec.description}\n"
    text += "使用该工具时，请在 agent_name 参数中指定要使用的agent名称，并在 task_text 中提供具体的任务文本。"
    return text


@subagent_toolset.tool(
    prepare=prepare_subagent,
    name="subagent",
    description=build_description_for_subagent(),
)
async def subagent(
    ctx: RunContext[ModelDeps],
    agent_name: Annotated[SubagentName, Field(description="要调用的子Agent名称")],
    task_text: Annotated[str, Field(description="要交给子Agent执行的任务文本")],
) -> str:
    if agent_name not in SUBAGENT_REGISTRY:
        raise ModelRetry(f"未知的agent名称: {agent_name}，可用agent: {list(SUBAGENT_REGISTRY.keys())}")

    agent = get_subagent(agent_name)

    result = await agent.run(
        user_prompt=task_text,
        model=ctx.model,
        deps=ctx.deps,
        model_settings=ctx.model_settings,
        output_type=str,
    )

    return result.output

from typing import Annotated, Literal

from pydantic import Field
from pydantic_ai import FunctionToolset, ModelRetry, RunContext, ToolDefinition
from pydantic_monty import Monty
from rich.pretty import pretty_repr

from .struct import ModelDeps

code_toolset: FunctionToolset[ModelDeps] = FunctionToolset()


async def prepare_code(ctx: RunContext[ModelDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    if "code_toolkit" in ctx.deps.select_toolset:
        return tool_def
    return None


@code_toolset.tool(
    name="python_repl",
    description="这是一个可以执行Python代码的工具，输入Python代码并返回最后一条表达式的结果和控制台输出。"
    "为了沙盒的安全性，以及沙盒的局限性，该工具不支持任何需要使用import导入的库，除了sys, typing, asyncio",
    prepare=prepare_code,
)
async def python_repl(
    ctx: RunContext[ModelDeps],
    code: Annotated[str, Field(description="要执行的Python代码")],
) -> Annotated[str, Field(description="返回最后一行表达式的结果和控制台输出")]:
    try:
        monty = Monty(code=code)
        out = []

        def print_callback(stream: Literal["stdout"], content: str) -> None:
            if stream == "stdout":
                out.append(content)

        result = await monty.run_async(print_callback=print_callback)
        output = "表达式结果: " + pretty_repr(result)
        if out:
            output += "\n输出:\n" + "".join(out)
        return output
    except Exception as e:
        raise ModelRetry(f"执行Python代码时发生错误: {e}") from e

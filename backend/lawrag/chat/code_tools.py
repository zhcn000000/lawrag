import re
from collections.abc import Callable
from typing import Annotated, Any, Literal
from uuid import uuid7

from pydantic import Field, TypeAdapter
from pydantic_ai import ModelRetry, RunContext, ToolDefinition
from pydantic_ai.capabilities import Capability
from pydantic_ai.messages import ToolCallPart, ToolReturn, ToolReturnContent, is_multi_modal_content
from pydantic_ai.tool_manager import ToolManager
from pydantic_ai.tools import ToolDenied
from pydantic_monty import Monty
from rich.pretty import pretty_repr

from .struct import ModelDeps

code_capability: Capability[ModelDeps] = Capability()

VALID_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


async def prepare_code(ctx: RunContext[ModelDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    if "code_toolkit" in ctx.deps.select_toolset:
        return tool_def
    return None


@code_capability.instructions
def code_instructions(ctx: RunContext[ModelDeps]) -> str | None:
    if "code_toolkit" not in ctx.deps.select_toolset:
        return None
    text = """当前已经启用了代码执行功能，你可以使用python_repl工具来执行Python代码。"""
    return text


@code_capability.tool(
    name="python_repl",
    description="""这是一个可以执行Python代码的工具，输入Python代码并返回最后一条表达式的结果和控制台输出。
为了沙盒的安全性，以及沙盒的局限性，该工具不支持部分标准库和所有第三方库的使用，且不支持网络请求。
其他工具作为同名同参数列表异步函数可以在Python代码中被调用，返回值为工具的返回值。
这个注入只会在名称为python合法标识符时才会成功，并且不允许递归调用python_repl自身。""",
    prepare=prepare_code,
    include_return_schema=True,
)
async def python_repl(
    ctx: RunContext[ModelDeps],
    code: Annotated[str, Field(description="要执行的Python代码")],
) -> Annotated[str, Field(description="返回最后一行表达式的结果和控制台输出")]:
    try:
        monty = Monty(code=code)
        out: list[str] = []

        def print_callback(stream: Literal["stdout"], content: str) -> None:
            if stream == "stdout":
                out.append(content)

        external_functions = _build_external_functions(ctx)

        result = await monty.run_async(
            external_functions=external_functions,
            print_callback=print_callback,
        )
        output = "表达式结果: " + pretty_repr(result)
        if out:
            output += "\n输出:\n" + "".join(out)
        return output
    except Exception as e:
        raise ModelRetry(f"执行Python代码时发生错误: {e}") from e


def _build_external_functions(ctx: RunContext[ModelDeps]) -> dict[str, Callable[..., Any]]:
    """从 Agent 的可用工具构建 Monty external_functions 字典，跳过 python_repl 自身和无效标识符。"""
    tool_manager = ctx.tool_manager
    if tool_manager is None or tool_manager.tools is None:
        return {}

    external_funcs: dict[str, Callable[..., Any]] = {}
    for name in tool_manager.tools:
        if name == "python_repl":
            continue
        if not VALID_IDENT.match(name):
            continue
        external_funcs[name] = _make_tool_wrapper(name, tool_manager)

    return external_funcs


def _make_tool_wrapper(name: str, tool_manager: ToolManager[ModelDeps]) -> Callable[..., Any]:
    """创建一个 async wrapper，使 pydantic-ai 工具可作为 Monty external function 使用。"""

    async def wrapper(**kwargs: Any) -> Any:
        call_part = ToolCallPart(tool_name=name, args=kwargs, tool_call_id=f"repl_{name}_{uuid7()}")
        result = await tool_manager.handle_call(call_part, wrap_validation_errors=False)
        if isinstance(result, ToolReturn):
            result = result.return_value
            if is_multi_modal_content(result):
                raise RuntimeError(f"工具 '{name}' 返回了 media 结果，无法在 Python REPL 中使用")
        if isinstance(result, ToolDenied):
            raise RuntimeError(f"工具 '{name}' 调用被拒绝")
        return TypeAdapter(ToolReturnContent).dump_python(result)

    return wrapper

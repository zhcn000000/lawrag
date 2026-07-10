import logging
from datetime import UTC, datetime

from pydantic_ai import Agent, ModelSettings, RunContext

from .chat_model import get_model
from .code_tools import code_capability
from .rag_tools import rag_capability
from .struct import TOOL_REGISTRY, ModelDeps
from .subagent_tools import subagent_capability
from .web_tools import web_capability

logger = logging.getLogger(__name__)

model = get_model()

agent: Agent[ModelDeps, str] = Agent(
    model=model,
    deps_type=ModelDeps,
    output_type=str,
    capabilities=[rag_capability, code_capability, web_capability, subagent_capability],
    retries=5,
)


@agent.instructions
async def metadata_prompt(ctx: RunContext[ModelDeps]):
    time = datetime.now(UTC).isoformat()
    model_name = ctx.model.model_name
    prompt = """你是一名专业的中国法律顾问AI助手。
请优先使用中文输出和<think>思考</think>，除非用户使用其他语言输入或明确要求使用其他语言。

你可以：
- 根据法律文档库中的法律法规回答用户的法律问题
- 引用具体的法律条文、条款和页码
- 对法律问题进行分析、解读和建议
- 在需要的地方使用mermaid语法绘制流程图、时序图等

markdown格式渲染中支持Mermaid和Infographic图表扩展，可以在需要的地方使用mermaid语法绘制法律流程图、法律程序关系图等。

如果要引用外部图片、视频、音频等的链接需要使用对应的html标签来渲染，并且需要保证链接的有效性和安全性。
"""
    prompt += f"""\n
你是模型：{model_name}
当前时间是(UTC)：{time}
用户可选以下工具集: \n"""

    for tool_name, tool_info in TOOL_REGISTRY.items():
        prompt += f"- {tool_name}: {tool_info.label} - {tool_info.description}\n"

    prompt += """用户可以选择勾选你能使用的工具集，你只能使用用户勾选的工具集来完成任务。
工具集不是具体的某个工具名称，而是一系列工具组成的集合，例如rag_toolkit工具集包含了list_laws、search_documents等工具。"""
    if ctx.deps.select_toolset:
        prompt += """你当前可以使用以下工具集:"""
        prompt += ",".join(ctx.deps.select_toolset)
    else:
        prompt += """你当前没有可用的工具集。"""
    return prompt


def get_model_settings(
    thinking: bool = True,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    presence_penalty: float | None = None,
) -> ModelSettings:
    if thinking:
        return ModelSettings(
            max_tokens=max_tokens or 131072,
            temperature=temperature or 1.0,
            top_p=top_p or 0.95,
            presence_penalty=presence_penalty or 1.5,
            extra_body={
                "chat_template_kwargs": {
                    "enable_thinking": True,
                },
            },
        )
    return ModelSettings(
        max_tokens=max_tokens or 131072,
        temperature=temperature or 0.7,
        top_p=top_p or 0.8,
        presence_penalty=presence_penalty or 1.5,
        extra_body={
            "chat_template_kwargs": {
                "enable_thinking": False,
            },
        },
    )

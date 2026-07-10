import logging
import os
from datetime import UTC, datetime

from pydantic_ai import Agent, ModelSettings, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

from lawrag.environments import settings

from .chat_model import get_model
from .code_tools import code_capability
from .rag_tools import rag_capability
from .struct import TOOL_REGISTRY, ModelDeps
from .subagent_tools import subagent_capability
from .web_tools import web_capability

logger = logging.getLogger(__name__)

if settings.USE_SELFHOSTED_LLM:
    model = get_model()
elif os.environ.get("DEEPSEEK_API_KEY"):
    model = OpenAIChatModel(model_name="deepseek-v4-flash", provider=DeepSeekProvider())
else:
    model = None
    logger.warning("DEEPSEEK_API_KEY not found in environment variables. The agent will not function without a model.")

agent: Agent[ModelDeps, str] = Agent(
    model=model,
    deps_type=ModelDeps,
    output_type=str,
    capabilities=[rag_capability, code_capability, web_capability, subagent_capability],
    retries=5,
    instructions="""你是一名专业的中国法律顾问AI助手。
请优先使用中文输出和<think>思考</think>，除非用户使用其他语言输入或明确要求使用其他语言。

你可以：
- 根据法律文档库中的法律法规回答用户的法律问题
- 引用具体的法律条文、条款和页码
- 对法律问题进行分析、解读和建议
- 在需要的地方使用mermaid语法绘制流程图、时序图等

markdown格式渲染中支持Mermaid和Infographic图表扩展，可以在需要的地方使用mermaid语法绘制法律流程图、法律程序关系图等。

如果要引用外部图片、视频、音频等的链接需要使用对应的html标签来渲染，并且需要保证链接的有效性和安全性。
""",
)


@agent.instructions
async def metadata_prompt(ctx: RunContext[ModelDeps]):
    time = datetime.now(UTC).isoformat()
    model_name = ctx.model.model_name

    prompt = f"""
你是模型：{model_name}
当前时间是(UTC)：{time}
你可能具有以下工具组合: \n"""

    for tool_name, tool_info in TOOL_REGISTRY.items():
        prompt += f"- {tool_name}: {tool_info.label} - {tool_info.description}\n"

    prompt += "用户可以选择勾选你能使用的工具组合，你只能使用用户勾选的工具组合来完成任务。\n"

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
            }
            if settings.USE_SELFHOSTED_LLM
            else {"thinking": {"type": "enabled"}},
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
        }
        if settings.USE_SELFHOSTED_LLM
        else {"thinking": {"type": "disabled"}},
    )

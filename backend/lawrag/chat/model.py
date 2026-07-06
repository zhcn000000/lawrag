import logging
import os
from datetime import UTC, datetime

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

from lawrag.utils.templete import FIRST_INPUT_TEMPLATE

from .struct import ModelDeps
from .tools import code_toolset, rag_toolset, web_toolset

if os.environ.get("DEEPSEEK_API_KEY"):
    model = OpenAIChatModel(model_name="deepseek-v4-flash", provider=DeepSeekProvider())
else:
    model = None
    logging.warning("DEEPSEEK_API_KEY not found in environment variables. The agent will not function without a model.")
agent: Agent[ModelDeps, str] = Agent(
    model=model,
    deps_type=ModelDeps,
    output_type=str,
    toolsets=[rag_toolset, code_toolset, web_toolset],
    instructions=FIRST_INPUT_TEMPLATE,
    retries=5,
)


@agent.instructions
async def metadata_prompt(ctx: RunContext[ModelDeps]):
    time = datetime.now(UTC).isoformat()
    model_name = ctx.model.model_name

    prompt = f"""
    你是模型：{model_name}
    当前时间是(UTC)：{time}"""
    return prompt

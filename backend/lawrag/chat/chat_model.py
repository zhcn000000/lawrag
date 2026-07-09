from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionUserMessageParam,
)
from pydantic_ai import (
    AudioUrl,
    BinaryContent,
    DocumentUrl,
    ImageUrl,
    ModelProfile,
    UserPromptPart,
    VideoUrl,
)
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers import Provider

from lawrag.environments import settings

BASE_URL = str(settings.LLM_LINK).removesuffix("/")
API_KEY = "sk-"
CHAT_MODEL = "qwen3.5"


class VLLMChatModel(OpenAIChatModel):
    async def _map_user_prompt(self, part: UserPromptPart) -> ChatCompletionUserMessageParam:
        content: str | list[dict]
        if isinstance(part.content, str):
            content = part.content
        else:
            content = []
            for item in part.content:
                if isinstance(item, str):
                    content.append({"type": "text", "text": item})
                elif isinstance(item, ImageUrl):
                    content.append({"type": "image_url", "image_url": {"url": item.url}})
                elif isinstance(item, AudioUrl):
                    content.append({"type": "audio_url", "audio_url": {"url": item.url}})
                elif isinstance(item, VideoUrl):
                    content.append({"type": "video_url", "video_url": {"url": item.url}})
                elif isinstance(item, DocumentUrl):
                    content.append({"type": "document_url", "document_url": {"url": item.url}})
                elif isinstance(item, BinaryContent):
                    if item.is_image:
                        content.append({"type": "image_url", "image_url": {"url": item.data_uri}})
                    elif item.is_audio:
                        content.append({"type": "audio_url", "audio_url": {"url": item.data_uri}})
                    elif item.is_video:
                        content.append({"type": "video_url", "video_url": {"url": item.data_uri}})
                    else:
                        content.append({"type": "document_url", "document_url": {"url": item.data_uri}})
                else:
                    raise ValueError(f"Unsupported content item type: {type(item)}")
        return ChatCompletionUserMessageParam(
            role="user",
            content=content,  # type: ignore
        )


def vllm_model_profile(model_name: str) -> ModelProfile:
    return OpenAIModelProfile(
        supports_tools=True,
        supports_image_output=True,
        supports_json_schema_output=True,
        supports_json_object_output=True,
        supports_tool_return_schema=True,
        supports_thinking=True,
        default_structured_output_mode="native",
        openai_chat_send_back_thinking_parts="field",
        openai_chat_thinking_field="reasoning",
    )


class VLLMProvider(Provider[AsyncOpenAI]):
    @property
    def name(self) -> str:
        return "vllm"

    @property
    def base_url(self) -> str:
        return BASE_URL

    @staticmethod
    def model_profile(model_name: str) -> ModelProfile | None:
        return vllm_model_profile(model_name)

    @property
    def client(self) -> AsyncOpenAI:
        return self._client

    def __init__(self) -> None:
        self._client = AsyncOpenAI(base_url=BASE_URL, api_key=API_KEY)


def get_model(
    model_name: str | None = None,
) -> Model:
    if model_name is None:
        model_name = CHAT_MODEL
    return VLLMChatModel(
        model_name=model_name,
        provider=VLLMProvider(),
    )

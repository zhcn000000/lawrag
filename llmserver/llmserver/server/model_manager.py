"""模型管理器 - 负责启动和管理 vLLM 模型实例."""

import json
import os
from collections.abc import AsyncGenerator
from logging import getLogger
from pathlib import Path
from typing import Any

from anyio import Path as AsyncPath
from anyio import open_file as aopen
from fastapi import HTTPException, UploadFile
from fastapi.requests import Request
from pydantic import BaseModel
from starlette.responses import JSONResponse, Response, StreamingResponse
from vllm import SamplingParams, TextPrompt
from vllm.engine.arg_utils import AsyncEngineArgs
from vllm.entrypoints.anthropic.protocol import AnthropicMessagesRequest, AnthropicMessagesResponse
from vllm.entrypoints.anthropic.serving import AnthropicServingMessages
from vllm.entrypoints.chat_utils import ChatTemplateConfig, load_chat_template
from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionRequest, ChatCompletionResponse
from vllm.entrypoints.openai.chat_completion.serving import OpenAIServingChat
from vllm.entrypoints.openai.completion.protocol import CompletionRequest, CompletionResponse
from vllm.entrypoints.openai.completion.serving import OpenAIServingCompletion
from vllm.entrypoints.openai.engine.protocol import (
    ErrorResponse,
    ModelCard,
    ModelList,
    OpenAIBaseModel,
    RequestResponseMetadata,
    UsageInfo,
)
from vllm.entrypoints.openai.models.protocol import BaseModelPath
from vllm.entrypoints.openai.models.serving import OpenAIServingModels
from vllm.entrypoints.openai.responses.protocol import ResponsesRequest, ResponsesResponse, StreamingResponsesResponse
from vllm.entrypoints.openai.responses.serving import OpenAIServingResponses
from vllm.entrypoints.pooling.classify.protocol import ClassificationRequest
from vllm.entrypoints.pooling.classify.serving import ServingClassification
from vllm.entrypoints.pooling.embed.protocol import CohereEmbedRequest, EmbeddingRequest
from vllm.entrypoints.pooling.embed.serving import ServingEmbedding
from vllm.entrypoints.pooling.pooling.protocol import PoolingRequest
from vllm.entrypoints.pooling.pooling.serving import ServingPooling
from vllm.entrypoints.pooling.scoring.protocol import RerankRequest, ScoreRequest
from vllm.entrypoints.pooling.scoring.serving import ServingScores
from vllm.entrypoints.scale_out.token_in_token_out.protocol import GenerateRequest, GenerateResponse
from vllm.entrypoints.scale_out.token_in_token_out.serving import ServingTokens
from vllm.entrypoints.serve.engine.serving import BaseServing
from vllm.entrypoints.serve.tokenize.protocol import (
    DetokenizeRequest,
    DetokenizeResponse,
    TokenizeRequest,
    TokenizeResponse,
)
from vllm.entrypoints.serve.tokenize.serving import ServingTokenization
from vllm.entrypoints.serve.utils.request_logger import RequestLogger
from vllm.entrypoints.speech_to_text.transcription.protocol import (
    TranscriptionRequest,
    TranscriptionResponse,
    TranscriptionResponseVerbose,
)
from vllm.entrypoints.speech_to_text.transcription.serving import OpenAIServingTranscription
from vllm.entrypoints.speech_to_text.translation.protocol import (
    TranslationRequest,
    TranslationResponse,
    TranslationResponseVerbose,
)
from vllm.entrypoints.speech_to_text.translation.serving import OpenAIServingTranslation
from vllm.renderers.online_renderer import OnlineRenderer
from vllm.v1.engine.async_llm import AsyncLLM

from .media_processer import audio_processer, document_processer, image_processer
from .templete import get_template

logger = getLogger(__name__)


class HandleType(BaseModel):
    completion: OpenAIServingCompletion | None = None
    chat_completion: OpenAIServingChat | None = None
    response: OpenAIServingResponses | None = None
    embedding: ServingEmbedding | None = None
    classify: ServingClassification | None = None
    score: ServingScores | None = None
    tokens: ServingTokens | None = None
    messages: AnthropicServingMessages | None = None
    transcription: OpenAIServingTranscription | None = None
    translation: OpenAIServingTranslation | None = None
    tokenize: ServingTokenization | None = None
    pooling: ServingPooling | None = None
    models: OpenAIServingModels | None = None
    render: OnlineRenderer | None = None

    class Config:
        arbitrary_types_allowed = True


class OCRRequest(OpenAIBaseModel):
    file: UploadFile
    prompt: str | None = None
    stream: bool = False
    model: str


class OCRResponse(OpenAIBaseModel):
    id: str
    text: str
    usage: UsageInfo


class ModelInstance(BaseModel):
    """模型实例."""

    model_uid: str
    model_name: str
    model_type: str | None = None
    engine: AsyncLLM
    handle: HandleType
    config: dict[str, Any]

    class Config:
        arbitrary_types_allowed = True


class ModelManager:
    def __init__(self) -> None:
        self.models: dict[str, ModelInstance] = {}

    async def load_models_from_config(self, config_path: Path | str | None = None) -> None:
        """从配置文件加载模型."""
        if config_path is None:
            msg = "必须提供模型配置文件路径"
            raise ValueError(msg)

        config_path_obj = AsyncPath(config_path)

        if not await config_path_obj.exists():
            msg = f"未找到模型配置文件: {config_path_obj}"
            raise FileNotFoundError(msg)

        async with await aopen(config_path_obj, "rb") as f:
            try:
                json_content = await f.read()
                launch_specs = json.loads(json_content)
            except json.JSONDecodeError as e:
                msg = f"解析模型配置 JSON 失败: {e}"
                raise ValueError(msg) from e

        if not isinstance(launch_specs, list):
            msg = "模型配置文件的顶层结构必须是 JSON 数组。"
            raise ValueError(msg)

        # 串行启动所有模型（支持 GPU 选择）
        for spec in launch_specs:
            if not isinstance(spec, dict):
                continue
            enabled = spec.get("enabled", True)
            if not enabled:
                continue

            try:
                await self._load_single_model(spec)
            except Exception as e:
                logger.exception(f"模型{spec.get('model')}启动失败，{e}")
                continue

    async def _load_single_model(self, spec: dict[str, Any]) -> str:
        """加载单个模型，支持 GPU 选择."""
        model_name = spec.get("model")
        model_uid = spec.get("model_uid", model_name)
        model_type = spec.get("model_type", "LLM")
        engine_args = spec.get("engine_args", {})
        if model_type == "LLM":
            engine_args["runner"] = "generate"
        elif model_type == "embedding":
            engine_args["runner"] = "pooling"
            engine_args["convert"] = "embed"
        elif model_type in {"rerank", "classify"}:
            engine_args["runner"] = "pooling"
            engine_args["convert"] = "classify"
        elif model_type in {"asr", "ocr"}:
            engine_args["runner"] = "generate"
        else:
            raise ValueError("Unknown model_type")
        if not model_uid or not model_name:
            msg = f"模型配置缺少 model_uid 或 model_name: {spec}"
            raise ValueError(msg)
        original_cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES")
        try:
            gpu_idx = spec.get("gpu_idx")  # 支持指定 GPU ID 列表，如 [0, 1]
            if gpu_idx is not None:
                # 使用指定的 GPU 列表
                if isinstance(gpu_idx, int):
                    gpu_idx = [gpu_idx]
                os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(map(str, gpu_idx))
            else:
                # 未指定 GPU，使用默认配置
                pass
            # 设置模型类型对应的 runner 和 convert
            engine_args["model"] = model_name

            # 构建 vLLM 引擎参数
            engine_args_obj = AsyncEngineArgs(**engine_args)

            # 创建异步引擎
            engine = AsyncLLM.from_engine_args(engine_args_obj)

            handle = await self._build_handle(engine, spec)

            # 存储模型实例

            self.models[model_uid] = ModelInstance(
                model_uid=model_uid,
                model_name=model_name,
                engine=engine,
                handle=handle,
                config=spec,
            )

            return model_uid

        finally:
            # 恢复原始 CUDA_VISIBLE_DEVICES 环境变量
            if original_cuda_visible is not None:
                os.environ["CUDA_VISIBLE_DEVICES"] = original_cuda_visible
            elif "CUDA_VISIBLE_DEVICES" in os.environ:
                del os.environ["CUDA_VISIBLE_DEVICES"]

    @staticmethod
    async def _build_handle(engine: AsyncLLM, spec: dict[str, Any]) -> HandleType:
        handle = HandleType()
        model_name = spec.get("model", "")
        model_type = spec.get("model_type", "LLM")
        model_uid = spec.get("model_uid", model_name)
        if model_type == "LLM":
            support_tasks = ("generate",)
        elif model_type == "embedding":
            support_tasks = ("embed", "pooling")
        elif model_type == "rerank":
            support_tasks = ("score", "pooling")
        elif model_type == "classify":
            support_tasks = ("classify", "pooling")
        elif model_type == "asr":
            support_tasks = ("generate", "transcription")
        elif model_type == "ocr":
            support_tasks = ("generate",)
        else:
            raise ValueError(f"未知的模型类型: {model_type}")
        if not model_name:
            msg = "模型配置缺少 'model' 字段"
            raise ValueError(msg)
        if spec.get("chat_template") is None:
            chat_template_content = get_template(model_name)
            if chat_template_content is not None:
                spec["chat_template"] = chat_template_content

        base_model_paths = [BaseModelPath(name=model_uid, model_path=model_name)]

        # 配置日志记录器
        logger = RequestLogger(max_log_len=spec.get("max_log_len"))

        # 获取模型支持的任务类型
        engine_supported_tasks = await engine.get_supported_tasks()

        # 加载 chat template
        chat_template_config = ChatTemplateConfig(
            chat_template=load_chat_template(
                chat_template=spec.get("chat_template"),
            ),
            chat_template_content_format=spec.get("chat_template_content_format", "auto"),
            trust_request_chat_template=spec.get("trust_request_chat_template", False),
        )

        # 创建 models handler
        handle.models = OpenAIServingModels(
            engine_client=engine,
            base_model_paths=base_model_paths,
        )

        # 创建 OnlineRenderer (vLLM 0.25+ requires this for all generate-serving classes)
        handle.render = OnlineRenderer(
            model_config=engine.model_config,
            renderer=engine.renderer,
            request_logger=logger,
            chat_template=chat_template_config.chat_template,
            chat_template_content_format=chat_template_config.chat_template_content_format,
            trust_request_chat_template=chat_template_config.trust_request_chat_template,
            enable_auto_tools=spec.get("enable_auto_tool_choice", False),
            exclude_tools_when_tool_choice_none=spec.get("exclude_tools_when_tool_choice_none", False),
            tool_parser=spec.get("tool_call_parser"),
            reasoning_parser=spec.get("reasoning_parser"),
            default_chat_template_kwargs=spec.get("default_chat_template_kwargs"),
            log_error_stack=spec.get("log_error_stack", True),
        )

        # 创建 tokenization handler
        handle.tokenize = ServingTokenization(
            models=handle.models,
            online_renderer=handle.render,
            request_logger=logger,
            chat_template=chat_template_config.chat_template,
            chat_template_content_format=chat_template_config.chat_template_content_format,
            trust_request_chat_template=chat_template_config.trust_request_chat_template,
        )

        # 创建 pooling handler
        if "pooling" in support_tasks:
            handle.pooling = ServingPooling(
                engine_client=engine,
                models=handle.models,
                supported_tasks=engine_supported_tasks,
                request_logger=logger,
                chat_template_config=chat_template_config,
                log_error_stack=spec.get("log_error_stack", True),
            )

        # 创建 generate 相关 handlers
        enable_auto_tools = False
        if "generate" in support_tasks:
            enable_auto_tools = spec.get("enable_auto_tool_choice")
            if enable_auto_tools is None:
                if spec.get("tool_call_parser"):
                    enable_auto_tools = True
                else:
                    enable_auto_tools = False
            handle.chat_completion = OpenAIServingChat(
                engine_client=engine,
                models=handle.models,
                response_role=spec.get("response_role", "assistant"),
                online_renderer=handle.render,
                request_logger=logger,
                chat_template=chat_template_config.chat_template,
                chat_template_content_format=chat_template_config.chat_template_content_format,
                trust_request_chat_template=chat_template_config.trust_request_chat_template,
                return_tokens_as_token_ids=spec.get("return_tokens_as_token_ids", False),
                enable_auto_tools=enable_auto_tools,
                exclude_tools_when_tool_choice_none=spec.get("exclude_tools_when_tool_choice_none", False),
                tool_parser=spec.get("tool_call_parser"),
                reasoning_parser=spec.get("reasoning_parser", ""),
                enable_prompt_tokens_details=spec.get("enable_prompt_tokens_details", True),
                enable_force_include_usage=spec.get("enable_force_include_usage", True),
                enable_log_outputs=spec.get("enable_log_outputs", False),
            )
            handle.response = OpenAIServingResponses(
                engine_client=engine,
                models=handle.models,
                online_renderer=handle.render,
                request_logger=logger,
                chat_template=chat_template_config.chat_template,
                chat_template_content_format=chat_template_config.chat_template_content_format,
                return_tokens_as_token_ids=spec.get("return_tokens_as_token_ids", False),
                enable_auto_tools=enable_auto_tools,
                tool_parser=spec.get("tool_call_parser"),
                reasoning_parser=spec.get("reasoning_parser", ""),
                enable_prompt_tokens_details=spec.get("enable_prompt_tokens_details", True),
                enable_force_include_usage=spec.get("enable_force_include_usage", True),
                enable_log_outputs=spec.get("enable_log_outputs", False),
            )
            handle.completion = OpenAIServingCompletion(
                engine_client=engine,
                models=handle.models,
                online_renderer=handle.render,
                request_logger=logger,
                return_tokens_as_token_ids=spec.get("return_tokens_as_token_ids", False),
                enable_prompt_tokens_details=spec.get("enable_prompt_tokens_details", True),
                enable_force_include_usage=spec.get("enable_force_include_usage", True),
            )
            handle.messages = AnthropicServingMessages(
                engine_client=engine,
                models=handle.models,
                response_role=spec.get("response_role", "assistant"),
                online_renderer=handle.render,
                request_logger=logger,
                chat_template=chat_template_config.chat_template,
                chat_template_content_format=chat_template_config.chat_template_content_format,
                enable_auto_tools=enable_auto_tools,
                tool_parser=spec.get("tool_call_parser"),
                reasoning_parser=spec.get("reasoning_parser", ""),
                enable_force_include_usage=spec.get("enable_force_include_usage", True),
                enable_prompt_tokens_details=spec.get("enable_prompt_tokens_details", True),
            )
            handle.tokens = ServingTokens(
                engine_client=engine,
                models=handle.models,
                online_renderer=handle.render,
                request_logger=logger,
                return_tokens_as_token_ids=spec.get("return_tokens_as_token_ids", False),
                enable_prompt_tokens_details=spec.get("enable_prompt_tokens_details", True),
                force_no_detokenize=spec.get("tokens_only", False),
                enable_log_outputs=spec.get("enable_log_outputs", True),
            )
            if handle.chat_completion is not None:
                handle.chat_completion.warmup()

        # 创建 embedding handler
        if "embed" in support_tasks:
            handle.embedding = ServingEmbedding(
                engine_client=engine,
                models=handle.models,
                request_logger=logger,
                chat_template_config=chat_template_config,
                log_error_stack=spec.get("log_error_stack", True),
            )

        # 创建 classify handler
        if "classify" in support_tasks:
            handle.classify = ServingClassification(
                engine_client=engine,
                models=handle.models,
                request_logger=logger,
                chat_template_config=chat_template_config,
                log_error_stack=spec.get("log_error_stack", True),
            )

        # 创建 score handler
        if "score" in support_tasks:
            handle.score = ServingScores(
                engine_client=engine,
                supported_tasks=engine_supported_tasks,
                models=handle.models,
                request_logger=logger,
                chat_template_config=chat_template_config,
                log_error_stack=spec.get("log_error_stack", True),
            )

        # 创建 transcription/translation handlers
        if "transcription" in support_tasks:
            handle.transcription = OpenAIServingTranscription(
                engine_client=engine,
                models=handle.models,
                request_logger=logger,
                return_tokens_as_token_ids=spec.get("return_tokens_as_token_ids", False),
                enable_force_include_usage=spec.get("enable_force_include_usage", True),
            )
            handle.translation = OpenAIServingTranslation(
                engine_client=engine,
                models=handle.models,
                request_logger=logger,
                return_tokens_as_token_ids=spec.get("return_tokens_as_token_ids", False),
                enable_force_include_usage=spec.get("enable_force_include_usage", True),
            )

        return handle

    def get_model(self, model_uid: str) -> ModelInstance | None:
        """获取模型实例."""
        return self.models.get(model_uid)

    async def list_models(self) -> ModelList:
        """列出所有模型."""
        model_cards: list[ModelCard] = []
        for model in self.models.values():
            if model.handle.models is not None:
                model_list = await model.handle.models.show_available_models()
                model_cards.extend(model_list.data)

        def _key(model_card: ModelCard) -> tuple[str, str]:
            return model_card.object, model_card.id

        model_cards.sort(key=_key)
        return ModelList(data=model_cards)

    def shutdown(self) -> None:
        """关闭所有模型."""
        for model in self.models.values():
            model.engine.shutdown()
        self.models.clear()

    def __del__(self) -> None:
        self.shutdown()

    async def create_chat_completion(
        self,
        request: ChatCompletionRequest,
        raw_request: Request | None = None,
    ) -> Response:
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")
        server = self.models[model].handle.chat_completion
        if server is None:
            raise HTTPException(404, "模型不支持该接口")
        model_config = self.models[model].config
        if model_config.get("enable_document_processer", False):
            request.messages = await document_processer(request.messages)
        if model_config.get("enable_audio_processer", False):
            request.messages = await audio_processer(
                request.messages,
                self,
                model=model_config.get("audio_processer_model"),
            )
        if model_config.get("enable_image_processer", False):
            request.messages = await image_processer(
                request.messages,
                self,
                model=model_config.get("image_processer_model"),
            )
        generator = await server.create_chat_completion(
            request=request,
            raw_request=raw_request,
        )
        if isinstance(generator, ErrorResponse):
            return JSONResponse(content=generator.model_dump(), status_code=generator.error.code)
        if isinstance(generator, ChatCompletionResponse):
            return JSONResponse(content=generator.model_dump())
        return StreamingResponse(content=generator, media_type="text/event-stream")

    async def create_responses(
        self,
        request: ResponsesRequest,
        raw_request: Request | None = None,
    ) -> Response:
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")

        server = self.models[model].handle.response
        if server is None:
            raise HTTPException(404, "模型不支持该接口")
        generator = await server.create_responses(
            request=request,
            raw_request=raw_request,
        )
        if isinstance(generator, ErrorResponse):
            return JSONResponse(content=generator.model_dump(), status_code=generator.error.code)
        if isinstance(generator, ResponsesResponse):
            return JSONResponse(content=generator.model_dump())

        async def _convert_stream_to_sse_events(
            gen: AsyncGenerator[StreamingResponsesResponse],
        ) -> AsyncGenerator[str]:
            async for event in gen:
                event_type = getattr(event, "type", "unknown")
                event_data = f"event: {event_type}\ndata: {event.model_dump_json(indent=None)}\n\n"
                yield event_data

        return StreamingResponse(content=_convert_stream_to_sse_events(generator), media_type="text/event-stream")

    async def create_messages(
        self,
        request: AnthropicMessagesRequest,
        raw_request: Request | None = None,
    ) -> Response:
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")

        server = self.models[model].handle.messages
        if server is None:
            raise HTTPException(404, "模型不支持该接口")
        generator = await server.create_messages(
            request=request,
            raw_request=raw_request,
        )
        if isinstance(generator, ErrorResponse):
            return JSONResponse(content=generator.model_dump(), status_code=generator.error.code)
        if isinstance(generator, AnthropicMessagesResponse):
            return JSONResponse(content=generator.model_dump(exclude_none=True))
        return StreamingResponse(content=generator, media_type="text/event-stream")

    async def create_embedding(
        self,
        request: EmbeddingRequest,
        raw_request: Request | None = None,
    ) -> Response:
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")

        server = self.models[model].handle.embedding
        if server is None:
            raise HTTPException(404, "模型不支持该接口")

        return await server(request, raw_request)

    async def create_embed(
        self,
        request: CohereEmbedRequest,
        raw_request: Request | None = None,
    ) -> Response:
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")

        server = self.models[model].handle.embedding
        if server is None:
            raise HTTPException(404, "模型不支持该接口")

        return await server(request, raw_request)

    async def create_rerank(
        self,
        request: RerankRequest,
        raw_request: Request | None = None,
    ) -> Response:
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")

        server = self.models[model].handle.score
        if server is None:
            raise HTTPException(404, "模型不支持该接口")

        return await server(request, raw_request)

    async def create_tokenize(
        self,
        request: TokenizeRequest,
        raw_request: Request | None = None,
    ) -> Response:
        """分词接口."""
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")

        server = self.models[model].handle.tokenize
        if server is None:
            raise HTTPException(404, "模型不支持分词功能")

        if raw_request is None:
            raise HTTPException(500, "raw_request is required for tokenize")
        generator = await server.create_tokenize(request, raw_request)
        if isinstance(generator, ErrorResponse):
            return JSONResponse(content=generator.model_dump(), status_code=generator.error.code)
        if isinstance(generator, TokenizeResponse):
            return JSONResponse(content=generator.model_dump())
        raise HTTPException(500, "模型分词接口返回了未知的响应类型")

    async def create_detokenize(
        self,
        request: DetokenizeRequest,
        raw_request: Request | None = None,
    ) -> Response:
        """反分词接口."""
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")

        server = self.models[model].handle.tokenize
        if server is None:
            raise HTTPException(404, "模型不支持反分词功能")

        if raw_request is None:
            raise HTTPException(500, "raw_request is required for detokenize")
        generator = await server.create_detokenize(request, raw_request)
        if isinstance(generator, ErrorResponse):
            return JSONResponse(content=generator.model_dump(), status_code=generator.error.code)
        if isinstance(generator, DetokenizeResponse):
            return JSONResponse(content=generator.model_dump())
        raise HTTPException(500, "模型反分词接口返回了未知的响应类型")

    async def serve_tokens(
        self,
        request: GenerateRequest,
        raw_request: Request | None = None,
    ) -> Response:
        """Tokens 接口."""
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")

        server = self.models[model].handle.tokens
        if server is None:
            raise HTTPException(404, "模型不支持 Tokens 接口")

        generator = await server.serve_tokens(request, raw_request)
        if isinstance(generator, ErrorResponse):
            return JSONResponse(content=generator.model_dump(), status_code=generator.error.code)
        if isinstance(generator, GenerateResponse):
            return JSONResponse(content=generator.model_dump())
        return StreamingResponse(content=generator, media_type="text/event-stream")

    async def create_completion(
        self,
        request: CompletionRequest,
        raw_request: Request | None = None,
    ) -> Response:
        """文本补全接口."""
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")

        server = self.models[model].handle.completion
        if server is None:
            raise HTTPException(404, "模型不支持该接口")

        generator = await server.create_completion(
            request=request,
            raw_request=raw_request,
        )
        if isinstance(generator, ErrorResponse):
            return JSONResponse(content=generator.model_dump(), status_code=generator.error.code)
        if isinstance(generator, CompletionResponse):
            return JSONResponse(content=generator.model_dump())
        return StreamingResponse(content=generator, media_type="text/event-stream")

    async def create_pooling(
        self,
        request: PoolingRequest,
        raw_request: Request | None = None,
    ) -> Response:
        """Pooling 接口."""
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")

        server = self.models[model].handle.pooling
        if server is None:
            raise HTTPException(404, f"模型 {model} 不支持 Pooling")

        return await server(request, raw_request)

    async def create_classify(
        self,
        request: ClassificationRequest,
        raw_request: Request | None = None,
    ) -> Response:
        """分类接口."""
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")

        server = self.models[model].handle.classify
        if server is None:
            raise HTTPException(404, f"模型 {model} 不是分类模型")

        return await server(request, raw_request)  # type: ignore[return-value]

    async def create_score(
        self,
        request: ScoreRequest,
        raw_request: Request | None = None,
    ) -> Response:
        """评分接口."""
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")

        server = self.models[model].handle.score
        if server is None:
            raise HTTPException(404, f"模型 {model} 不支持评分")

        return await server(request, raw_request)

    async def create_transcription(
        self,
        audio_data: bytes,
        request: TranscriptionRequest,
        raw_request: Request | None = None,
    ) -> Response:
        """音频转写接口."""
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")

        server = self.models[model].handle.transcription
        if server is None:
            raise HTTPException(404, "模型不支持该接口")

        generator = await server.create_transcription(
            audio_data=audio_data,
            request=request,
            raw_request=raw_request,
        )
        if isinstance(generator, ErrorResponse):
            return JSONResponse(content=generator.model_dump(), status_code=generator.error.code)
        if isinstance(generator, (TranscriptionResponse, TranscriptionResponseVerbose)):
            return JSONResponse(content=generator.model_dump())
        return StreamingResponse(content=generator, media_type="text/event-stream")

    async def create_translation(
        self,
        audio_data: bytes,
        request: TranslationRequest,
        raw_request: Request | None = None,
    ) -> Response:
        """音频翻译接口."""
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")

        server = self.models[model].handle.translation
        if server is None:
            raise HTTPException(404, "模型不支持该接口")

        generator = await server.create_translation(
            audio_data=audio_data,
            request=request,
            raw_request=raw_request,
        )
        if isinstance(generator, ErrorResponse):
            return JSONResponse(content=generator.model_dump(), status_code=generator.error.code)
        if isinstance(generator, (TranslationResponse, TranslationResponseVerbose)):
            return JSONResponse(content=generator.model_dump())
        return StreamingResponse(content=generator, media_type="text/event-stream")

    async def create_ocr(
        self,
        image_data: bytes,
        request: OCRRequest,
        raw_request: Request | None = None,
    ) -> Response:
        """OCR 接口."""
        model = request.model
        if not model or model not in self.models:
            raise HTTPException(404, f"模型 {model} 未找到")

        engine = self.models[model].engine
        if engine is None:
            raise HTTPException(404, "模型不支持该接口")
        request_id = f"ocr-{BaseServing._base_request_id(raw_request)}"
        prompt = TextPrompt(
            prompt=request.prompt or "<image>\nDo OCR",
            multi_modal_data={"image": image_data},
        )
        sample_params = SamplingParams(skip_special_tokens=False)
        generator = engine.generate(prompt, sample_params, request_id)
        if request.stream:

            async def stream_generator():
                previous_text = ""
                async for output in generator:
                    for completion_output in output.outputs:
                        current_text = completion_output.text
                        new_text = current_text[len(previous_text) :]
                        previous_text = current_text
                        if new_text:
                            yield f"data: {new_text}\n\n"

            return StreamingResponse(content=stream_generator(), media_type="text/event-stream")
        request_output = None
        async for output in generator:
            if output.finished:
                request_output = output
                break
        assert request_output is not None, "Failed to get OCR output."
        completion_output = request_output.outputs[-1]
        text = completion_output.text
        prompt_tokens = len(request_output.prompt_token_ids) if request_output.prompt_token_ids else 0
        usage = UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=len(completion_output.token_ids),
            total_tokens=prompt_tokens + len(completion_output.token_ids),
        )
        request_metadata = RequestResponseMetadata(request_id=request_id, final_usage_info=usage)
        return JSONResponse(content=OCRResponse(text=text, id=request_metadata.request_id, usage=usage).model_dump())

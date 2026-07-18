from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from lawrag.eval.eval import evaluate, evaluate_stream
from lawrag.routers.schema import EvalRequest, EvalResponse

from .user import CurrentUserDep

router = APIRouter(dependencies=[CurrentUserDep])


@router.post("/run")
async def api_eval_run(request: EvalRequest) -> EvalResponse:
    reports = await evaluate(request.cases, offline=request.offline)
    return EvalResponse(reports=reports)


@router.post("/run-stream")
async def api_eval_run_stream(request: EvalRequest) -> StreamingResponse:
    async def stream_generator() -> AsyncIterator[str]:
        async for report in evaluate_stream(request.cases, offline=request.offline):
            yield f"data: {report.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")

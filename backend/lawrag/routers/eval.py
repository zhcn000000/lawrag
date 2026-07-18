from fastapi import APIRouter

from lawrag.eval.eval import evaluate
from lawrag.routers.schema import EvalRequest, EvalResponse

from .user import CurrentUserDep

router = APIRouter(dependencies=[CurrentUserDep])


@router.post("/run")
async def api_eval_run(request: EvalRequest) -> EvalResponse:
    reports = await evaluate(request.cases, offline=request.offline)
    return EvalResponse(reports=reports)

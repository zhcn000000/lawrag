from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles

from lawrag.database.user import TokenDataDict, UserManager
from lawrag.routers.user import CurrentUserDep
from lawrag.tools.mcp import mcp
from lawrag.utils.environments import find_project_directory

from .chat import router as chat_router
from .rag import router as rag_router
from .schema import (
    StatusResponse,
    TokenResponse,
    UserCredentialsRequest,
    UserResponse,
)
from .user import router as user_router

mcp_app = mcp.http_app()
app = FastAPI(lifespan=mcp_app.lifespan)
app.mount("/mcp", mcp_app, name="mcp")
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])
app.include_router(rag_router, prefix="/api/rag", tags=["rag"])
app.include_router(user_router, prefix="/api/users", tags=["users"])
static_path = find_project_directory() / "static"
if static_path.exists() and static_path.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

user_manager = UserManager()


@app.post("/api/login")
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]) -> TokenResponse:
    token = await user_manager.averify_credentials(form_data.username, form_data.password)
    if token is None:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    return TokenResponse(access_token=token)


@app.post("/api/register")
async def register(request: UserCredentialsRequest) -> StatusResponse:
    try:
        await user_manager.ainsert(request.username, request.password)
    except Exception as e:
        raise HTTPException(status_code=409, detail="Username already exists") from e
    return StatusResponse(success=True, status="用户注册成功")


@app.post("/api/refresh")
async def refresh_token(
    token_data: Annotated[TokenDataDict, CurrentUserDep],
) -> TokenResponse:
    token = await user_manager.acreate_access_token(token_data["username"])
    return TokenResponse(access_token=token)


@app.get("/api/me")
async def get_current_user(
    token_data: Annotated[TokenDataDict, CurrentUserDep],
) -> UserResponse:
    user_info = await user_manager.aget(token_data["user_id"])
    if user_info is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(id=user_info["id"], username=user_info["username"])


__all__ = ["chat_router", "rag_router", "user_router"]

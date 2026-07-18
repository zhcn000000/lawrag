from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles

from lawrag.chat.agent import ModelDeps, agent
from lawrag.database.user import TokenDataDict, UserManager
from lawrag.environments import find_project_directory, settings
from lawrag.routers.user import CurrentUserDep

from .chat import router as chat_router
from .kb import router as kb_router
from .rag import router as rag_router
from .schema import (
    StatusResponse,
    TokenResponse,
    UserCredentialsRequest,
    UserResponse,
)
from .user import router as user_router

app = FastAPI()
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])
app.include_router(kb_router, prefix="/api/kb", tags=["kb"])
app.include_router(rag_router, prefix="/api/rag", tags=["rag"])
app.include_router(user_router, prefix="/api/users", tags=["users"])

static_path = find_project_directory() / "static"
if static_path.exists() and static_path.is_dir():
    assets_path = static_path / "assets"
    app.mount("/webui/assets", StaticFiles(directory=str(assets_path)), name="assets")

    @app.get("/webui/favicon.svg", include_in_schema=False)
    @app.get("/favicon.svg", include_in_schema=False)
    async def serve_favicon():
        return FileResponse(static_path / "favicon.svg")

    @app.get("/webui/{path:path}", include_in_schema=False)
    async def serve_webui(path: str):
        return FileResponse(static_path / "index.html")

else:

    @app.get("/webui/{path:path}", include_in_schema=False)
    async def serve_webui_nofound(path: str):
        raise HTTPException(status_code=404, detail="Web UI not found")


user_manager = UserManager()


@app.get("/", include_in_schema=False)
@app.get("/webui", include_in_schema=False)
@app.get("/webui/", include_in_schema=False)
async def redirect_to_webui():
    return RedirectResponse(url="/webui/index.html")


@app.post("/api/login")
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], response: Response) -> TokenResponse:
    token = await user_manager.averify_credentials(form_data.username, form_data.password)
    if token is None:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    response.set_cookie(key="lawrag_token", value=token, httponly=True, max_age=settings.TOKEN_EXPIRES_IN, secure=True)
    return TokenResponse(access_token=token)


@app.post("/api/register")
async def register(request: UserCredentialsRequest) -> StatusResponse:
    try:
        await user_manager.ainsert(request.username, request.password)
    except Exception as e:
        raise HTTPException(status_code=409, detail="Username already exists") from e
    return StatusResponse(success=True, status="用户注册成功")


@app.post("/api/refresh")
async def refresh_token(token_data: Annotated[TokenDataDict, CurrentUserDep], response: Response) -> TokenResponse:
    token = await user_manager.acreate_access_token(
        token_data["user_id"],
        token_data["username"],
        "admin" in token_data["scopes"],
    )
    response.set_cookie(key="lawrag_token", value=token, httponly=True, max_age=settings.TOKEN_EXPIRES_IN, secure=True)
    return TokenResponse(access_token=token)


@app.get("/api/me")
async def get_current_user(
    token_data: Annotated[TokenDataDict, CurrentUserDep],
) -> UserResponse:
    user_info = await user_manager.aget(token_data["user_id"])
    if user_info is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(id=user_info["id"], username=user_info["username"], is_admin=user_info["is_admin"])


__all__ = ["ModelDeps", "agent", "app", "chat_router", "kb_router", "rag_router", "user_router"]

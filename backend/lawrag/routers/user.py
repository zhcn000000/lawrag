from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from lawrag.database.user import TokenDataDict, UserManager

from .schema import (
    StatusResponse,
    UpdateUserRequest,
    UserCredentialsRequest,
    UserListResponse,
    UserResponse,
)

router = APIRouter()
user_manager = UserManager()

CurrentUserDep = Depends(UserManager.get_current_user)


@router.get("/")
async def list_users(
    token_data: Annotated[TokenDataDict, CurrentUserDep],
) -> UserListResponse:
    users = await user_manager.alists()
    return UserListResponse(users=[UserResponse(id=v["id"], username=v["username"]) for v in users.values()])


@router.put("/")
async def create_user(
    request: UserCredentialsRequest,
    token_data: Annotated[TokenDataDict, CurrentUserDep],
) -> UserResponse:
    try:
        user_id = await user_manager.ainsert(request.username, request.password)
    except Exception as e:
        raise HTTPException(status_code=409, detail="Username already exists") from e
    return UserResponse(id=user_id, username=request.username)


@router.get("/{user_id}")
async def get_user(
    user_id: UUID,
    token_data: Annotated[TokenDataDict, CurrentUserDep],
) -> UserResponse:
    user_info = await user_manager.aget(user_id)
    if user_info is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(id=user_info["id"], username=user_info["username"])


@router.delete("/{user_id}")
async def delete_user(
    user_id: UUID,
    token_data: Annotated[TokenDataDict, CurrentUserDep],
) -> StatusResponse:
    if token_data["user_id"] != user_id and token_data["username"] != "admin":
        raise HTTPException(status_code=403, detail="Cannot delete other users")
    await user_manager.adelete(user_id)
    return StatusResponse(success=True, status="用户删除成功")


@router.patch("/{user_id}")
async def update_user(
    user_id: UUID,
    request: UpdateUserRequest,
    token_data: Annotated[TokenDataDict, CurrentUserDep],
) -> StatusResponse:
    if token_data["user_id"] != user_id and token_data["username"] != "admin":
        raise HTTPException(status_code=403, detail="Cannot update other users")
    await user_manager.aupdate(user_id, username=request.username, password=request.password)
    return StatusResponse(success=True, status="用户更新成功")

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import SecurityScopes

from lawrag.database.history import HistoryStore
from lawrag.database.user import ALGORITHM, UserManager
from lawrag.environments import settings


def _make_token(
    username: str,
    user_id: UUID,
    expires_in: int = 300,
    secret: str | None = None,
    scopes: list[str] | None = None,
) -> str:
    payload = {
        "sub": username,
        "user_id": str(user_id),
        "scopes": scopes or [],
        "exp": datetime.now(UTC) + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, secret or settings.JWT_SECRET.get_secret_value(), algorithm=ALGORITHM)


def test_verify_access_token_roundtrip():
    user_id = uuid4()
    token = _make_token("alice", user_id)
    data = UserManager.verify_access_token(token)
    assert data is not None
    assert data["username"] == "alice"
    assert data["user_id"] == user_id
    assert data["scopes"] == []

    admin_token = _make_token("root", user_id, scopes=["admin"])
    admin_data = UserManager.verify_access_token(admin_token)
    assert admin_data is not None
    assert admin_data["scopes"] == ["admin"]


def test_verify_access_token_expired():
    token = _make_token("alice", uuid4(), expires_in=-10)
    with pytest.raises(HTTPException) as exc_info:
        UserManager.verify_access_token(token)
    assert exc_info.value.status_code == 401


def test_verify_access_token_wrong_secret():
    token = _make_token("alice", uuid4(), secret="not-the-real-secret-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    with pytest.raises(HTTPException) as exc_info:
        UserManager.verify_access_token(token)
    assert exc_info.value.status_code == 401


def test_get_current_user_rejects_invalid_token():
    with pytest.raises(HTTPException) as exc_info:
        UserManager.get_current_user(SecurityScopes(), "garbage-token")
    assert exc_info.value.status_code == 401


def test_get_current_user_enforces_admin_scope():
    admin = UserManager.get_current_user(SecurityScopes(["admin"]), _make_token("root", uuid4(), scopes=["admin"]))
    assert "admin" in admin["scopes"]

    with pytest.raises(HTTPException) as exc_info:
        UserManager.get_current_user(SecurityScopes(["admin"]), _make_token("alice", uuid4()))
    assert exc_info.value.status_code == 403


@pytest.fixture(scope="module")
def client():
    from lawrag.routers import app  # ruff:ignore[unsorted-imports, import-outside-top-level]  # to map httpx -> httpx2
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/me"),
        ("POST", "/api/refresh"),
        ("GET", "/api/users/"),
        ("PUT", "/api/users/"),
        ("GET", "/api/chat/list"),
        ("GET", "/api/chat/tools"),
        ("POST", "/api/chat/"),
        ("POST", "/api/rag/search"),
        ("GET", "/api/rag/pageindex/laws"),
    ],
)
def test_endpoints_require_auth(client, method: str, path: str):
    response = client.request(method, path)
    assert response.status_code == 401


def test_valid_token_passes_auth(client):
    token = _make_token("alice", uuid4())
    response = client.get("/api/chat/tools", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_expired_token_rejected_by_endpoint(client):
    token = _make_token("alice", uuid4(), expires_in=-10)
    response = client.get("/api/chat/tools", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.db
async def test_credentials_and_session_isolation():
    um = UserManager()
    hs = HistoryStore()
    name_a = f"test_auth_a_{uuid4().hex[:8]}"
    name_b = f"test_auth_b_{uuid4().hex[:8]}"
    id_a = await um.ainsert(name_a, "password-a")
    id_b = await um.ainsert(name_b, "password-b")
    try:
        assert await um.averify_credentials(name_a, "password-a") is not None
        with pytest.raises(HTTPException) as exc_info:
            UserManager.get_current_user(SecurityScopes(), "invalid-token")
            assert exc_info.value.status_code == 401

        session_id = await hs.acreate_session("会话A", id_a)
        assert await hs.acheck_session_exists(session_id, id_a)
        assert not await hs.acheck_session_exists(session_id, id_b)

        assert any(s["session_id"] == session_id for s in await hs.alist_sessions(id_a))
        assert all(s["session_id"] != session_id for s in await hs.alist_sessions(id_b))

        assert not await hs.arename_session(session_id, "hacked", id_b)
        assert not await hs.adelete_session(session_id, id_b)
        assert await hs.arename_session(session_id, "会话A2", id_a)
        assert await hs.adelete_session(session_id, id_a)
    finally:
        await um.adelete(id_a)
        await um.adelete(id_b)

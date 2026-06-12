import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

# Some legacy regression modules replace core.auth with a minimal shared stub.
if "core.auth" in sys.modules:
    setattr(sys.modules["core.auth"], "RESERVED_USERNAMES", set())

from routes.auth_routes import ChangePasswordRequest, setup_auth_routes
from src.desktop_biometric import (
    BIOMETRIC_SECRET_ENV,
    issue_biometric_token,
    verify_biometric_token,
)


class FakeAuthManager:
    def __init__(self):
        self.users = {"rowiz": {"is_admin": True}}
        self.is_configured = True
        self.signup_enabled = False
        self.changed = []
        self.set_without_password = []
        self.revoked = []

    def get_username_for_token(self, _token):
        return None

    def change_password(self, username, current_password, new_password):
        self.changed.append((username, current_password, new_password))
        return current_password == "old-password"

    def set_password(self, username, new_password, requesting_user, allow_self):
        self.set_without_password.append(
            (username, new_password, requesting_user, allow_self)
        )
        return True

    def revoke_user_sessions(self, username, except_token=None):
        self.revoked.append((username, except_token))
        return 0


def _request(*, forwarded=False):
    headers = [(b"x-forwarded-for", b"127.0.0.1")] if forwarded else []
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/change-password",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 54321),
            "server": ("127.0.0.1", 7001),
            "scheme": "http",
            "app": SimpleNamespace(state=SimpleNamespace()),
        }
    )


def _change_password_endpoint(auth_manager):
    router = setup_auth_routes(auth_manager)
    return next(
        route.endpoint
        for route in router.routes
        if route.path == "/api/auth/change-password"
    )


@pytest.fixture
def desktop_env(monkeypatch):
    monkeypatch.setenv("LOCALHOST_BYPASS", "true")
    monkeypatch.setenv("ODYSSEUS_DESKTOP", "1")
    monkeypatch.setenv(BIOMETRIC_SECRET_ENV, "test-secret-" * 5)


def test_biometric_token_is_bound_to_user_and_expiry():
    secret = "test-secret-" * 5
    token = issue_biometric_token("Rowiz", secret=secret, now=1000)

    assert verify_biometric_token(token, "rowiz", secret=secret, now=1020)
    assert verify_biometric_token(token, "someone-else", secret=secret, now=1020) is None
    assert verify_biometric_token(token, "rowiz", secret=secret, now=1100) is None
    assert verify_biometric_token(token + "x", "rowiz", secret=secret, now=1020) is None


@pytest.mark.asyncio
async def test_desktop_password_change_requires_existing_password_or_touch_id(desktop_env):
    auth = FakeAuthManager()
    endpoint = _change_password_endpoint(auth)

    with pytest.raises(HTTPException) as exc:
        await endpoint(
            ChangePasswordRequest(new_password="new-password"),
            _request(),
        )

    assert exc.value.status_code == 400
    assert "Current password or Touch ID" in exc.value.detail
    assert auth.changed == []
    assert auth.set_without_password == []


@pytest.mark.asyncio
async def test_desktop_password_change_verifies_current_password(desktop_env):
    auth = FakeAuthManager()
    endpoint = _change_password_endpoint(auth)

    with pytest.raises(HTTPException) as exc:
        await endpoint(
            ChangePasswordRequest(
                current_password="wrong-password",
                new_password="new-password",
            ),
            _request(),
        )
    assert exc.value.status_code == 400
    assert auth.set_without_password == []

    result = await endpoint(
        ChangePasswordRequest(
            current_password="old-password",
            new_password="new-password",
        ),
        _request(),
    )
    assert result == {"ok": True}
    assert auth.changed[-1] == ("rowiz", "old-password", "new-password")
    assert auth.set_without_password == []


@pytest.mark.asyncio
async def test_touch_id_proof_is_native_only_and_single_use(desktop_env):
    auth = FakeAuthManager()
    endpoint = _change_password_endpoint(auth)
    token = issue_biometric_token("rowiz")
    body = ChangePasswordRequest(
        new_password="new-password",
        biometric_token=token,
    )

    with pytest.raises(HTTPException) as exc:
        await endpoint(body, _request(forwarded=True))
    assert exc.value.status_code == 401

    result = await endpoint(body, _request())
    assert result == {"ok": True}
    assert auth.set_without_password == [
        ("rowiz", "new-password", "rowiz", True)
    ]

    with pytest.raises(HTTPException) as exc:
        await endpoint(body, _request())
    assert exc.value.status_code == 400
    assert "invalid or expired" in exc.value.detail

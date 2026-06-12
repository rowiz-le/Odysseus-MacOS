"""Short-lived signed proofs for native desktop biometric authorization."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, Optional


BIOMETRIC_SECRET_ENV = "ODYSSEUS_DESKTOP_BIOMETRIC_SECRET"
BIOMETRIC_TOKEN_TTL = 75
_MAX_TOKEN_LIFETIME = 120
_TOKEN_PURPOSE = "change_password"


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _secret_bytes(secret: Optional[str] = None) -> bytes:
    value = (secret or os.environ.get(BIOMETRIC_SECRET_ENV, "")).strip()
    if len(value) < 32:
        raise RuntimeError("Desktop biometric signing secret is unavailable")
    return value.encode("utf-8")


def issue_biometric_token(
    username: str,
    *,
    secret: Optional[str] = None,
    now: Optional[int] = None,
) -> str:
    """Issue a proof after native LocalAuthentication succeeds."""
    subject = (username or "").strip().lower()
    if not subject:
        raise ValueError("Username is required")

    issued_at = int(time.time() if now is None else now)
    payload = {
        "v": 1,
        "sub": subject,
        "purpose": _TOKEN_PURPOSE,
        "iat": issued_at,
        "exp": issued_at + BIOMETRIC_TOKEN_TTL,
        "nonce": secrets.token_urlsafe(18),
    }
    body = _encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        _secret_bytes(secret),
        body.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{body}.{_encode(signature)}"


def verify_biometric_token(
    token: str,
    username: str,
    *,
    secret: Optional[str] = None,
    now: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Validate a proof and return its payload, or None when it is invalid."""
    try:
        body, encoded_signature = token.split(".", 1)
        supplied_signature = _decode(encoded_signature)
        expected_signature = hmac.new(
            _secret_bytes(secret),
            body.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None

        payload = json.loads(_decode(body).decode("utf-8"))
        current_time = int(time.time() if now is None else now)
        issued_at = int(payload["iat"])
        expires_at = int(payload["exp"])
        if payload.get("v") != 1:
            return None
        if payload.get("sub") != (username or "").strip().lower():
            return None
        if payload.get("purpose") != _TOKEN_PURPOSE:
            return None
        if not isinstance(payload.get("nonce"), str) or not payload["nonce"]:
            return None
        if issued_at > current_time + 5 or expires_at <= current_time:
            return None
        if expires_at - issued_at > _MAX_TOKEN_LIFETIME:
            return None
        return payload
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError):
        return None

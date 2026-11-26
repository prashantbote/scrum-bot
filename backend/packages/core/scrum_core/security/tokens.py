"""Signed one-click links for emails (plan §10).

``token = base64url(json(payload)) + "." + base64url(HMAC-SHA256(secret, payload_b64))``

Blocker payload:  {k:"blocker", jti, org, blocker, rcpt, exp}
Check-in payload: {k:"checkin", jti, org, session, user, exp}

Tokens are stateless; single use per action is enforced by ``action_token_uses``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from scrum_core.settings import get_settings


class InvalidToken(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _secret() -> bytes:
    return get_settings().action_token_secret.get_secret_value().encode()


def sign(payload: dict[str, Any]) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    mac = hmac.new(_secret(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


@dataclass(frozen=True)
class ActionClaims:
    kind: Literal["blocker", "checkin"]
    token_id: str
    org_id: UUID
    expires_at: int
    blocker_id: UUID | None = None
    recipient: str | None = None
    session_id: UUID | None = None
    user_id: UUID | None = None

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at


def verify(token: str) -> ActionClaims:
    """Checks the signature. Expiry is reported (``claims.expired``), not raised, so the page can say so."""
    try:
        body, mac = token.split(".", 1)
        expected = hmac.new(_secret(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(mac)):
            raise InvalidToken("bad signature")
        p = json.loads(_unb64(body))
        kind = p["k"]
        if kind == "blocker":
            return ActionClaims(
                kind="blocker",
                token_id=p["jti"],
                org_id=UUID(p["org"]),
                expires_at=int(p["exp"]),
                blocker_id=UUID(p["blocker"]),
                recipient=str(p["rcpt"]),
            )
        if kind == "checkin":
            return ActionClaims(
                kind="checkin",
                token_id=p["jti"],
                org_id=UUID(p["org"]),
                expires_at=int(p["exp"]),
                session_id=UUID(p["session"]),
                user_id=UUID(p["user"]),
            )
        raise InvalidToken("unknown kind")
    except InvalidToken:
        raise
    except Exception as exc:  # malformed base64 / json / uuid
        raise InvalidToken("malformed token") from exc


def blocker_token(*, org_id: UUID, blocker_id: UUID, recipient: str, ttl_seconds: int | None = None) -> str:
    ttl = ttl_seconds if ttl_seconds is not None else get_settings().action_token_ttl_days * 86_400
    return sign(
        {
            "k": "blocker",
            "jti": secrets.token_hex(8),
            "org": str(org_id),
            "blocker": str(blocker_id),
            "rcpt": recipient,
            "exp": int(time.time()) + ttl,
        }
    )


def checkin_token(*, org_id: UUID, session_id: UUID, user_id: UUID, expires_at: int) -> str:
    return sign(
        {
            "k": "checkin",
            "jti": secrets.token_hex(8),
            "org": str(org_id),
            "session": str(session_id),
            "user": str(user_id),
            "exp": expires_at,
        }
    )


def verify_payload(token: str, *, kind: str) -> dict[str, Any]:
    """Generic signed payload (e.g. OAuth ``state``). Raises InvalidToken on bad signature, kind or expiry."""
    try:
        body, mac = token.split(".", 1)
        expected = hmac.new(_secret(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(mac)):
            raise InvalidToken("bad signature")
        p: dict[str, Any] = json.loads(_unb64(body))
    except InvalidToken:
        raise
    except Exception as exc:
        raise InvalidToken("malformed token") from exc
    if p.get("k") != kind:
        raise InvalidToken("wrong kind")
    if int(p.get("exp", 0)) < time.time():
        raise InvalidToken("expired")
    return p

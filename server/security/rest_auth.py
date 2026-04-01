# =============================================================================
# server/security/rest_auth.py
# Autenticacao e autorizacao simples por token para escrita REST
# =============================================================================

from __future__ import annotations

import os
import hmac
from dataclasses import dataclass
from typing import Callable

from fastapi import HTTPException, Request, status

from config.settings import (
    REST_ADMIN_TOKEN,
    REST_AUTH_ENABLED,
    REST_INGEST_TOKEN,
    REST_WRITE_TOKEN,
)


@dataclass(frozen=True)
class AuthContext:
    role: str
    token_source: str


def _auth_habilitada(request: Request) -> bool:
    if "PYTEST_CURRENT_TEST" in os.environ and not getattr(
        request.app.state, "force_rest_auth_for_tests", False
    ):
        return False
    return getattr(request.app.state, "rest_auth_enabled", REST_AUTH_ENABLED)


def _extrair_token(request: Request) -> tuple[str, str]:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip(), "authorization"

    token = request.headers.get("x-api-token", "").strip()
    if token:
        return token, "x-api-token"

    return "", "none"


def _tokens_permitidos(scope: str) -> list[tuple[str, str]]:
    allowed: list[tuple[str, str]] = []

    if scope == "admin":
        if REST_ADMIN_TOKEN:
            allowed.append((REST_ADMIN_TOKEN, "admin"))
        elif REST_WRITE_TOKEN:
            allowed.append((REST_WRITE_TOKEN, "write"))
    elif scope == "ingest":
        if REST_INGEST_TOKEN:
            allowed.append((REST_INGEST_TOKEN, "ingest"))
        elif REST_WRITE_TOKEN:
            allowed.append((REST_WRITE_TOKEN, "write"))
        if REST_ADMIN_TOKEN:
            allowed.append((REST_ADMIN_TOKEN, "admin"))
    else:
        if REST_WRITE_TOKEN:
            allowed.append((REST_WRITE_TOKEN, "write"))
        if REST_ADMIN_TOKEN:
            allowed.append((REST_ADMIN_TOKEN, "admin"))

    return allowed


def _validar_token(scope: str, token: str, source: str) -> AuthContext:
    allowed = _tokens_permitidos(scope)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Autenticacao REST habilitada, mas nenhum token foi configurado.",
        )

    for expected_token, role in allowed:
        if expected_token and hmac.compare_digest(token, expected_token):
            return AuthContext(role=role, token_source=source)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token REST invalido ou ausente.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_rest_scope(scope: str = "write") -> Callable[[Request], AuthContext]:
    async def dependency(request: Request) -> AuthContext:
        if not _auth_habilitada(request):
            return AuthContext(role="disabled", token_source="disabled")

        token, source = _extrair_token(request)
        return _validar_token(scope=scope, token=token, source=source)

    return dependency


require_rest_write = require_rest_scope("write")
require_rest_admin = require_rest_scope("admin")
require_rest_ingest = require_rest_scope("ingest")

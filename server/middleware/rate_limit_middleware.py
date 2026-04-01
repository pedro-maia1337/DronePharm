# =============================================================================
# server/middleware/rate_limit_middleware.py
# Rate limiting em memoria para endpoints caros ou sensiveis
# =============================================================================

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config.settings import (
    RATE_LIMIT_LOGS_POST_PER_MINUTE,
    RATE_LIMIT_ROTAS_CALCULAR_PER_MINUTE,
    RATE_LIMIT_ENABLED,
)


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window_s: int


_RATE_LIMIT_RULES: Dict[Tuple[str, str], RateLimitRule] = {
    ("POST", "/api/v1/rotas/calcular"): RateLimitRule(
        limit=RATE_LIMIT_ROTAS_CALCULAR_PER_MINUTE,
        window_s=60,
    ),
    ("POST", "/api/v1/logs/"): RateLimitRule(
        limit=RATE_LIMIT_LOGS_POST_PER_MINUTE,
        window_s=60,
    ),
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._hits: Dict[Tuple[str, str, str], Deque[float]] = defaultdict(deque)

    @staticmethod
    def _identidade_cliente(request: Request) -> str:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
        if request.client and request.client.host:
            return request.client.host
        return "unknown"

    def _verificar_limite(self, request: Request) -> tuple[bool, int]:
        regra = _RATE_LIMIT_RULES.get((request.method.upper(), request.url.path))
        if regra is None:
            return True, 0

        agora = time.monotonic()
        chave = (request.method.upper(), request.url.path, self._identidade_cliente(request))
        eventos = self._hits[chave]

        while eventos and (agora - eventos[0]) >= regra.window_s:
            eventos.popleft()

        if len(eventos) >= regra.limit:
            retry_after = max(1, int(regra.window_s - (agora - eventos[0])))
            return False, retry_after

        eventos.append(agora)
        return True, 0

    async def dispatch(self, request: Request, call_next):
        enabled = getattr(request.app.state, "rate_limit_enabled", RATE_LIMIT_ENABLED)
        force_in_tests = getattr(request.app.state, "force_rate_limit_for_tests", False)
        if "PYTEST_CURRENT_TEST" in os.environ and not force_in_tests:
            enabled = False

        if not enabled:
            return await call_next(request)

        permitido, retry_after = self._verificar_limite(request)
        if not permitido:
            return JSONResponse(
                status_code=429,
                content={
                    "erro": "Rate limit excedido.",
                    "detalhe": "Reduza a frequência das requisições e tente novamente.",
                    "path": str(request.url.path),
                    "metodo": request.method,
                },
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)

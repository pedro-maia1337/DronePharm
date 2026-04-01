# =============================================================================
# servidor/middleware/logging_middleware.py
# Middleware de log de acesso — registra método, path, status e duração
# de cada requisição recebida pelo servidor
# =============================================================================

import time
import uuid
import logging
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

from config.settings import (
    ACCESS_LOG_INCLUDE_QUERY_STRING,
    ACCESS_LOG_SENSITIVE_QUERY_PARAMS,
)

log = logging.getLogger("server.acesso")


def _query_string_sanitizada(request: Request) -> str:
    if not ACCESS_LOG_INCLUDE_QUERY_STRING or not request.url.query:
        return ""

    itens = []
    for chave, valor in request.query_params.multi_items():
        chave_normalizada = chave.lower()
        valor_log = "***" if chave_normalizada in ACCESS_LOG_SENSITIVE_QUERY_PARAMS else valor
        itens.append((chave, valor_log))

    return f"?{urlencode(itens, doseq=True)}" if itens else ""


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Loga todas as requisições HTTP recebidas com:
      - Método, path e query string
      - Status de resposta
      - Duração em milissegundos
      - ID único de requisição (X-Request-ID)

    O cabeçalho X-Request-ID é adicionado à resposta para rastreabilidade.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        req_id = str(uuid.uuid4())[:8]
        inicio = time.perf_counter()

        # Injeta ID na requisição para uso nos routers se necessário
        request.state.request_id = req_id

        try:
            response = await call_next(request)
        except Exception:
            # Deixa o ErrorHandlerMiddleware tratar — apenas loga aqui
            log.error(f"[{req_id}] Exceção durante {request.method} {request.url.path}")
            raise

        duracao_ms = (time.perf_counter() - inicio) * 1000

        # Escolhe nível de log pelo status
        nivel = logging.INFO
        if response.status_code >= 500:
            nivel = logging.ERROR
        elif response.status_code >= 400:
            nivel = logging.WARNING

        qs = _query_string_sanitizada(request)
        log.log(
            nivel,
            f"[{req_id}] {request.method} {request.url.path}{qs} "
            f"→ {response.status_code} ({duracao_ms:.1f}ms)",
        )

        # Adiciona headers de diagnóstico à resposta
        response.headers["X-Request-ID"]    = req_id
        response.headers["X-Process-Time"]  = f"{duracao_ms:.1f}ms"

        return response

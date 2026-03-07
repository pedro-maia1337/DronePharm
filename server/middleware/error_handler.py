# =============================================================================
# servidor/middleware/error_handler.py
# Middleware de tratamento global de erros — captura exceções não tratadas
# e retorna JSON estruturado em vez de traceback HTML
# =============================================================================

import logging
import traceback
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger("server.erros")


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """
    Captura qualquer exceção não tratada pelos routers e retorna uma resposta
    JSON padronizada com status 500, sem vazar stack traces para o cliente.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)

        except Exception as exc:
            # Log completo com traceback para diagnóstico interno
            log.error(
                f"Erro não tratado: {request.method} {request.url.path}\n"
                f"{traceback.format_exc()}"
            )
            return JSONResponse(
                status_code=500,
                content={
                    "erro":     "Erro interno do servidor.",
                    "detalhe":  str(exc),
                    "path":     str(request.url.path),
                    "metodo":   request.method,
                },
            )

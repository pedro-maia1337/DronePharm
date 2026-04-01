# =============================================================================
# tests/test_security_hardening.py
# Cobertura adicional de hardening sem alterar a suite existente
# =============================================================================

import os
import sys
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_engine_mock():
    result_mock = MagicMock()
    result_mock.scalar.return_value = "PostgreSQL 16 (mock)"
    conn_mock = AsyncMock()
    conn_mock.execute = AsyncMock(return_value=result_mock)
    engine_mock = MagicMock()
    engine_mock.connect = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn_mock),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    engine_mock.dispose = AsyncMock()
    return engine_mock


def _make_session_factory_mock():
    result_mock = MagicMock()
    result_mock.mappings.return_value.fetchone.return_value = None

    session_mock = AsyncMock()
    session_mock.execute = AsyncMock(return_value=result_mock)

    return MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=session_mock),
            __aexit__=AsyncMock(return_value=False),
        )
    )


@pytest.fixture
def client():
    from server.app import app
    from bd.database import get_db

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()
    mock_session.execute = AsyncMock()

    async def _fake_db():
        yield mock_session

    app.dependency_overrides[get_db] = _fake_db

    with patch("bd.database.engine", _make_engine_mock()), \
         patch("bd.database.AsyncSessionLocal", _make_session_factory_mock()), \
         patch("bd.database.init_db", AsyncMock()), \
         patch("bd.database.close_db", AsyncMock()), \
         patch("bd.database.check_db_connection", AsyncMock(return_value=True)):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


class TestSecurityHardening:
    def test_logging_middleware_redige_query_param_sensivel(self, client, caplog):
        with patch("server.routers.pedidos.PedidoRepository") as repo_cls:
            repo_cls.return_value.contar = AsyncMock(return_value=0)
            repo_cls.return_value.listar = AsyncMock(return_value=[])

            caplog.set_level(logging.INFO, logger="server.acesso")
            response = client.get("/api/v1/pedidos/?status=pendente&token=segredo")

        assert response.status_code == 200
        mensagens = [r.message for r in caplog.records if r.name == "server.acesso"]
        assert any("token=%2A%2A%2A" in mensagem for mensagem in mensagens)
        assert all("token=segredo" not in mensagem for mensagem in mensagens)

    def test_error_handler_omite_detalhe_interno_em_modo_seguro(self):
        from server.middleware.error_handler import ErrorHandlerMiddleware
        from server.middleware.logging_middleware import LoggingMiddleware

        app = FastAPI()
        app.add_middleware(LoggingMiddleware)
        app.add_middleware(ErrorHandlerMiddleware)

        @app.get("/boom")
        async def boom():
            raise RuntimeError("segredo interno do banco")

        with patch("server.middleware.error_handler.EXPOSE_INTERNAL_ERROR_DETAIL", False):
            with TestClient(app) as client_local:
                response = client_local.get("/boom")

        assert response.status_code == 500
        body = response.json()
        assert body["detalhe"] == "Consulte o suporte com o X-Request-ID."
        assert body["request_id"] is not None

    def test_ws_info_exige_token_quando_configurado(self, client):
        client.app.state.force_ws_info_auth_for_tests = True
        with patch("server.websocket.router_ws._WS_TOKEN", "segredo"), \
             patch("server.websocket.router_ws.WS_INFO_REQUIRE_AUTH", True):
            sem_token = client.get("/ws/info")
            com_token = client.get("/ws/info", headers={"x-ws-token": "segredo"})
        client.app.state.force_ws_info_auth_for_tests = False

        assert sem_token.status_code == 401
        assert com_token.status_code == 200

    def test_rate_limit_bloqueia_requisicoes_excessivas(self):
        from server.middleware.rate_limit_middleware import RateLimitMiddleware

        app = FastAPI()
        app.state.rate_limit_enabled = True
        app.state.force_rate_limit_for_tests = True
        app.add_middleware(RateLimitMiddleware)

        @app.post("/api/v1/rotas/calcular")
        async def calcular():
            return {"ok": True}

        with patch(
                 "server.middleware.rate_limit_middleware._RATE_LIMIT_RULES",
                 {("POST", "/api/v1/rotas/calcular"): type("Rule", (), {"limit": 2, "window_s": 60})()},
             ):
            with TestClient(app) as client_local:
                assert client_local.post("/api/v1/rotas/calcular").status_code == 200
                assert client_local.post("/api/v1/rotas/calcular").status_code == 200
                bloqueada = client_local.post("/api/v1/rotas/calcular")

        assert bloqueada.status_code == 429
        assert bloqueada.headers["Retry-After"]

    def test_logs_rejeita_payload_json_grande_demais(self, client):
        resposta = client.post(
            "/api/v1/logs/",
            json={
                "nivel": "INFO",
                "categoria": "SISTEMA",
                "mensagem": "Teste",
                "dados_json": {"blob": "x" * 20000},
            },
        )

        assert resposta.status_code == 422

# =============================================================================
# tests/test_api_contract_updates.py
# Cobertura adicional para contratos da API sem alterar a suite existente
# =============================================================================

import os
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _farmacia(id=1, deposito=False, ativa=True, criada_em=None):
    return SimpleNamespace(
        id=id,
        nome=f"Farmacia {id}",
        latitude=-19.93,
        longitude=-43.95,
        endereco="Rua X",
        cidade="Belo Horizonte",
        uf="MG",
        deposito=deposito,
        ativa=ativa,
        criada_em=criada_em,
    )


def _pedido(id=1, status="pendente"):
    return SimpleNamespace(
        id=id,
        latitude=-19.93,
        longitude=-43.95,
        peso_kg=0.5,
        prioridade=2,
        descricao="Dipirona 500mg",
        farmacia_id=1,
        rota_id=None,
        status=status,
        janela_fim=datetime(2026, 6, 1, 18, 0),
        criado_em=datetime(2025, 6, 1, 10, 0),
        entregue_em=None,
    )


def _drone(id="DP-01", status="aguardando"):
    return SimpleNamespace(
        id=id,
        nome=f"DronePharm-{id}",
        capacidade_max_kg=2.0,
        autonomia_max_km=10.0,
        velocidade_ms=10.0,
        bateria_pct=1.0,
        status=status,
        latitude_atual=None,
        longitude_atual=None,
        missoes_realizadas=5,
        cadastrado_em=datetime(2025, 1, 1),
        atualizado_em=datetime(2025, 1, 1),
    )


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

    factory = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=session_mock),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    return factory


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


class TestApiContractUpdates:

    def test_atualizar_pedido_usa_repositorio(self, client):
        atualizado = _pedido(id=7)
        atualizado.descricao = "Descricao atualizada"

        with patch("server.routers.pedidos.PedidoRepository") as repo_cls:
            repo_cls.return_value.buscar_por_id = AsyncMock(return_value=_pedido(id=7))
            repo_cls.return_value.atualizar = AsyncMock(return_value=atualizado)

            response = client.patch(
                "/api/v1/pedidos/7",
                json={"descricao": "Descricao atualizada"},
            )

        assert response.status_code == 200
        repo_cls.return_value.atualizar.assert_awaited_once_with(7, descricao="Descricao atualizada")

    def test_listar_pedidos_retorna_metadados_de_paginacao(self, client):
        with patch("server.routers.pedidos.PedidoRepository") as repo_cls:
            repo_cls.return_value.contar = AsyncMock(return_value=250)
            repo_cls.return_value.listar = AsyncMock(return_value=[_pedido(1), _pedido(2)])

            response = client.get("/api/v1/pedidos/?limite=2&offset=10")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["total_count"] == 250
        assert body["limit"] == 2
        assert body["offset"] == 10
        assert body["has_more"] is True

    def test_deposito_principal_aceita_criada_em_nulo_no_fallback(self, client):
        with patch("server.routers.farmacias.FarmaciaRepository") as repo_cls:
            repo_cls.return_value.buscar_deposito_principal = AsyncMock(
                return_value=_farmacia(deposito=True, criada_em=None)
            )

            response = client.get("/api/v1/farmacias/deposito")

        assert response.status_code == 200
        assert response.json()["criada_em"] is None

    def test_patch_drone_rejeita_status_fora_do_enum(self, client):
        response = client.patch("/api/v1/drones/DP-01", json={"status": "parado"})
        assert response.status_code == 422

    def test_recalculo_forcado_nao_permite_drone_em_voo(self, client):
        with patch("server.routers.rotas.PedidoRepository") as pedido_repo_cls, \
             patch("server.routers.rotas.DroneRepository") as drone_repo_cls:
            pedido_repo_cls.return_value.buscar_por_ids = AsyncMock(return_value=[_pedido(1)])
            drone_repo_cls.return_value.buscar_por_id = AsyncMock(return_value=_drone(status="em_voo"))

            response = client.post(
                "/api/v1/rotas/calcular",
                json={"drone_id": "DP-01", "pedido_ids": [1], "forcar_recalc": True},
            )

        assert response.status_code == 409

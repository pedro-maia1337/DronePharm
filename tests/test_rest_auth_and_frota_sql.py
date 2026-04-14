# =============================================================================
# tests/test_rest_auth_and_frota_sql.py
# Cobertura adicional para autenticacao REST e consulta segura da frota
# =============================================================================

import os
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _farmacia(id=1, deposito=False, ativa=True):
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
        criada_em=datetime(2025, 1, 1),
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
        latitude_atual=-19.93,
        longitude_atual=-43.95,
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
    app.state.force_rest_auth_for_tests = False

    _sync_telem = AsyncMock(
        return_value={"pedido_ids": [], "eta_seg": None, "eventos": []}
    )
    with patch("bd.database.engine", _make_engine_mock()), \
         patch("bd.database.AsyncSessionLocal", _make_session_factory_mock()), \
         patch("bd.database.init_db", AsyncMock()), \
         patch("bd.database.close_db", AsyncMock()), \
         patch("bd.database.check_db_connection", AsyncMock(return_value=True)), \
         patch("server.routers.telemetria.sincronizar_pedidos_apos_telemetria", _sync_telem):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


class TestRestAuthAndFrotaSql:
    def test_post_pedido_exige_token_quando_auth_ativada(self, client):
        client.app.state.force_rest_auth_for_tests = True
        client.app.state.rest_auth_enabled = True

        with patch("server.security.rest_auth.REST_WRITE_TOKEN", "write-token"):
            response = client.post(
                "/api/v1/pedidos/",
                json={
                    "coordenada": {"latitude": -19.93, "longitude": -43.95},
                    "peso_kg": 0.5,
                    "prioridade": 2,
                    "farmacia_id": 1,
                },
            )

        assert response.status_code == 401

    def test_post_pedido_aceita_token_de_escrita(self, client):
        client.app.state.force_rest_auth_for_tests = True
        client.app.state.rest_auth_enabled = True

        with patch("server.security.rest_auth.REST_WRITE_TOKEN", "write-token"), \
             patch("server.routers.pedidos.FarmaciaRepository") as farmacia_repo_cls, \
             patch("server.routers.pedidos.PedidoRepository") as pedido_repo_cls:
            farmacia_repo_cls.return_value.buscar_por_id = AsyncMock(return_value=_farmacia())
            pedido_repo_cls.return_value.criar = AsyncMock(return_value=_pedido(10))

            response = client.post(
                "/api/v1/pedidos/",
                json={
                    "coordenada": {"latitude": -19.93, "longitude": -43.95},
                    "peso_kg": 0.5,
                    "prioridade": 2,
                    "farmacia_id": 1,
                },
                headers={"x-api-token": "write-token"},
            )

        assert response.status_code == 201

    def test_entregar_pedido_exige_token_admin(self, client):
        client.app.state.force_rest_auth_for_tests = True
        client.app.state.rest_auth_enabled = True

        with patch("server.security.rest_auth.REST_WRITE_TOKEN", "write-token"), \
             patch("server.security.rest_auth.REST_ADMIN_TOKEN", "admin-token"), \
             patch("server.routers.pedidos.PedidoRepository") as repo_cls:
            repo_cls.return_value.buscar_por_id = AsyncMock(return_value=_pedido(1))

            response = client.patch(
                "/api/v1/pedidos/1/entregar",
                headers={"x-api-token": "write-token"},
            )

        assert response.status_code == 401

    def test_post_telemetria_aceita_token_de_ingestao(self, client):
        client.app.state.force_rest_auth_for_tests = True
        client.app.state.rest_auth_enabled = True

        registro = SimpleNamespace(
            id=1,
            drone_id="DP-01",
            latitude=-19.93,
            longitude=-43.95,
            altitude_m=50.0,
            velocidade_ms=10.0,
            bateria_pct=0.75,
            vento_ms=3.0,
            direcao_vento=180.0,
            status="em_voo",
            criado_em=datetime(2025, 6, 1, 12, 0),
        )

        with patch("server.security.rest_auth.REST_INGEST_TOKEN", "ingest-token"), \
             patch("server.routers.telemetria.DroneRepository") as drone_repo_cls, \
             patch("server.routers.telemetria.TelemetriaRepository") as telem_repo_cls, \
             patch("server.routers.telemetria.manager") as manager_mock:
            drone_repo_cls.return_value.buscar_por_id = AsyncMock(return_value=_drone())
            drone_repo_cls.return_value.atualizar_posicao_e_bateria = AsyncMock()
            drone_repo_cls.return_value.buscar_disponiveis = AsyncMock(return_value=[_drone()])
            telem_repo_cls.return_value.criar = AsyncMock(return_value=registro)
            manager_mock.broadcast_telemetria = AsyncMock()
            manager_mock.broadcast_alerta = AsyncMock()
            manager_mock.broadcast_status_frota = AsyncMock()

            response = client.post(
                "/api/v1/telemetria/",
                json={
                    "drone_id": "DP-01",
                    "latitude": -19.93,
                    "longitude": -43.95,
                    "altitude_m": 50.0,
                    "velocidade_ms": 10.0,
                    "bateria_pct": 0.75,
                    "vento_ms": 3.0,
                    "direcao_vento": 180.0,
                    "status": "em_voo",
                },
                headers={"authorization": "Bearer ingest-token"},
            )

        assert response.status_code == 201

    def test_status_frota_usa_consulta_segura_com_ids_especiais(self, client):
        row = {
            "drone_id": "DP'01",
            "latitude": -19.93,
            "longitude": -43.95,
            "criado_em": datetime(2025, 6, 1, 12, 0),
        }
        result = MagicMock()
        result.mappings.return_value.all.return_value = [row]

        with patch("server.routers.frota.DroneRepository") as drone_repo_cls:
            drone_repo_cls.return_value.listar = AsyncMock(return_value=[_drone(id="DP'01")])
            client.app.dependency_overrides.clear()

            from bd.database import get_db

            mock_session = AsyncMock()
            mock_session.commit = AsyncMock()
            mock_session.rollback = AsyncMock()
            mock_session.close = AsyncMock()
            mock_session.execute = AsyncMock(return_value=result)

            async def _fake_db():
                yield mock_session

            client.app.dependency_overrides[get_db] = _fake_db
            response = client.get("/api/v1/frota/status")
            client.app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 200

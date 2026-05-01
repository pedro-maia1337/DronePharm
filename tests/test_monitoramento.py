import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _rota():
    return SimpleNamespace(
        id=7,
        drone_id="DP-01",
        pedido_ids=[123, 124],
        status="em_execucao",
    )


def _pedido(pedido_id: int, status: str):
    return SimpleNamespace(
        id=pedido_id,
        latitude=-19.9213,
        longitude=-43.9456,
        status=status,
    )


def _drone():
    return SimpleNamespace(
        id="DP-01",
        velocidade_ms=14.0,
        latitude_atual=-19.9200,
        longitude_atual=-43.9440,
    )


def _telemetria():
    return SimpleNamespace(
        drone_id="DP-01",
        latitude=-19.9205,
        longitude=-43.9445,
        velocidade_ms=15.5,
        direcao_vento=120.0,
    )


def test_calcular_eta_segundos_retorna_estimativa_em_segundos():
    from server.services.monitoramento import calcular_eta_segundos

    eta = calcular_eta_segundos(
        latitude_atual=0.0,
        longitude_atual=0.0,
        destino_latitude=0.001,
        destino_longitude=0.0,
        velocidade_ms=10.0,
    )

    assert eta is not None
    assert 10 <= eta <= 12


@pytest.mark.asyncio
async def test_listar_snapshot_monitoramento_resolve_pedido_principal_por_drone():
    from server.services.monitoramento import listar_snapshot_monitoramento

    db = MagicMock()
    rota = _rota()
    pedido_despachado = _pedido(123, "despachado")
    pedido_em_voo = _pedido(124, "em_voo")
    drone = _drone()
    telemetria = _telemetria()

    with patch("server.services.monitoramento.RotaRepository") as rota_repo, \
         patch("server.services.monitoramento.PedidoRepository") as pedido_repo, \
         patch("server.services.monitoramento.DroneRepository") as drone_repo, \
         patch("server.services.monitoramento.TelemetriaRepository") as telemetria_repo:
        rota_repo.return_value.listar_por_status = AsyncMock(
            side_effect=[[rota], []]
        )
        pedido_repo.return_value.buscar_por_ids = AsyncMock(
            return_value=[pedido_despachado, pedido_em_voo]
        )
        drone_repo.return_value.buscar_por_ids = AsyncMock(return_value=[drone])
        telemetria_repo.return_value.buscar_ultimas_por_drones = AsyncMock(
            return_value={"DP-01": telemetria}
        )

        snapshot = await listar_snapshot_monitoramento(db)

    assert len(snapshot) == 1
    item = snapshot[0]
    assert item["drone_id"] == "DP-01"
    assert item["pedido_id"] == 124
    assert item["status_missao"] == "em_voo"
    assert item["posicao"]["lat"] == telemetria.latitude
    assert item["vetor"]["velocidade_ms"] == telemetria.velocidade_ms
    assert item["vetor"]["direcao"] == telemetria.direcao_vento
    assert item["eta_segundos"] is not None

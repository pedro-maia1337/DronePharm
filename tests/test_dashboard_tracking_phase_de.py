import os
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _pedido(
    pedido_id: int,
    *,
    status: str = "em_voo",
    rota_id: int | None = 10,
):
    agora = datetime.now()
    return SimpleNamespace(
        id=pedido_id,
        latitude=-19.92,
        longitude=-43.94,
        peso_kg=0.5,
        prioridade=1,
        descricao="Insulina",
        farmacia_id=1,
        rota_id=rota_id,
        status=status,
        janela_fim=agora + timedelta(hours=1),
        criado_em=agora - timedelta(minutes=15),
        entregue_em=None,
        despachado_em=agora - timedelta(minutes=10),
        estimativa_entrega_em=agora + timedelta(minutes=5),
    )


def _rota(rota_id: int, *, status: str = "em_execucao", drone_id: str = "DP-01"):
    return SimpleNamespace(
        id=rota_id,
        drone_id=drone_id,
        pedido_ids=[1],
        status=status,
        waypoints_json=[
            {"latitude": -19.91, "longitude": -43.93, "label": "Deposito"},
            {"latitude": -19.92, "longitude": -43.94, "label": "Pedido 1"},
        ],
        distancia_km=3.2,
        tempo_min=8.5,
        energia_wh=48.0,
        carga_kg=1.0,
        custo=0.42,
        viavel=True,
        geracoes_ga=12,
        criada_em=datetime.now(),
        concluida_em=None,
    )


def _drone(drone_id: str = "DP-01", *, status: str = "em_voo"):
    return SimpleNamespace(
        id=drone_id,
        nome="Drone",
        status=status,
        bateria_pct=0.81,
        latitude_atual=-19.915,
        longitude_atual=-43.935,
        missoes_realizadas=4,
        velocidade_ms=10.0,
    )


def _telemetria(drone_id: str = "DP-01"):
    return SimpleNamespace(
        id=77,
        drone_id=drone_id,
        latitude=-19.915,
        longitude=-43.935,
        altitude_m=48.0,
        velocidade_ms=10.5,
        bateria_pct=0.81,
        vento_ms=2.0,
        direcao_vento=180.0,
        status="em_voo",
        criado_em=datetime.now(),
    )


@pytest.mark.asyncio
async def test_geojson_snapshot_filtra_apenas_itens_ativos():
    from server.routers.mapa import geojson_snapshot

    db = MagicMock()
    deposito = SimpleNamespace(id=1, nome="Deposito", latitude=-19.9, longitude=-43.9)
    pedido_ativo = _pedido(1, status="despachado")
    drone_ativo = _drone("DP-01", status="em_voo")
    drone_inativo = _drone("DP-02", status="aguardando")
    drone_inativo.latitude_atual = -19.91
    drone_inativo.longitude_atual = -43.91

    with patch("server.routers.mapa.FarmaciaRepository") as farmacia_repo, \
         patch("server.routers.mapa.PedidoRepository") as pedido_repo, \
         patch("server.routers.mapa.RotaRepository") as rota_repo, \
         patch("server.routers.mapa.DroneRepository") as drone_repo:
        farmacia_repo.return_value.buscar_deposito_principal = AsyncMock(return_value=deposito)
        pedido_repo.return_value.listar = AsyncMock(return_value=[pedido_ativo])
        rota_repo.return_value.listar_por_status = AsyncMock(
            side_effect=[[_rota(10, status="em_execucao")], [_rota(11, status="calculada")]]
        )
        drone_repo.return_value.listar = AsyncMock(return_value=[drone_ativo, drone_inativo])

        snapshot = await geojson_snapshot(db=db)

    tipos = [feature["properties"]["tipo"] for feature in snapshot["features"]]
    assert "deposito" in tipos
    assert tipos.count("pedido") == 1
    assert tipos.count("rota_linha") == 2
    drones = [f for f in snapshot["features"] if f["properties"]["tipo"] == "drone"]
    assert len(drones) == 1
    assert drones[0]["properties"]["id"] == "DP-01"


@pytest.mark.asyncio
async def test_obter_pedido_ativo_retorna_payload_enriquecido():
    from server.services.pedido_tracking import obter_pedido_ativo

    db = MagicMock()
    pedido = _pedido(22, status="em_voo", rota_id=33)
    rota = _rota(33, status="em_execucao", drone_id="DP-07")
    drone = _drone("DP-07", status="em_voo")
    telemetria = _telemetria("DP-07")

    with patch("server.services.pedido_tracking.PedidoRepository") as pedido_repo, \
         patch("server.services.pedido_tracking.RotaRepository") as rota_repo, \
         patch("server.services.pedido_tracking.DroneRepository") as drone_repo, \
         patch("server.services.pedido_tracking.TelemetriaRepository") as telemetria_repo:
        pedido_repo.return_value.buscar_por_id = AsyncMock(return_value=pedido)
        rota_repo.return_value.buscar_por_id = AsyncMock(return_value=rota)
        drone_repo.return_value.buscar_por_id = AsyncMock(return_value=drone)
        telemetria_repo.return_value.buscar_ultima = AsyncMock(return_value=telemetria)

        payload = await obter_pedido_ativo(db, 22)

    assert payload is not None
    assert payload["pedido_id"] == 22
    assert payload["drone_id"] == "DP-07"
    assert payload["status"] == "em_voo"
    assert payload["tempo_decorrido_seg"] is not None
    assert payload["tempo_restante_seg"] is not None
    assert payload["posicao_atual"]["latitude"] == telemetria.latitude
    assert payload["destino"]["longitude"] == pedido.longitude


@pytest.mark.asyncio
async def test_kpis_tempo_real_agrega_metricas_operacionais():
    from server.routers.historico import kpis_tempo_real

    class ScalarResult:
        def __init__(self, value):
            self._value = value

        def scalar_one(self):
            return self._value

    class ScalarsResult:
        def __init__(self, values):
            self._values = values

        def scalars(self):
            return self

        def all(self):
            return self._values

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            ScalarResult(4),
            ScalarResult(2),
            ScalarResult(9),
            ScalarsResult(
                [
                    datetime.now() + timedelta(minutes=5),
                    datetime.now() + timedelta(minutes=15),
                ]
            ),
        ]
    )

    with patch("server.routers.historico.HistoricoRepository") as repo:
        repo.return_value.kpis_gerais = AsyncMock(
            return_value={"taxa_pontualidade_pct": 87.5}
        )
        out = await kpis_tempo_real(db=db)

    assert out.total_ativos == 4
    assert out.pedidos_em_voo == 2
    assert out.concluidos == 9
    assert out.pontualidade_pct == 87.5
    assert out.eta_medio_seg > 0


@pytest.mark.asyncio
async def test_pedido_repository_emite_evento_websocket_em_transicao_nao_telemetrica():
    from bd.repositories.pedido_repo import PedidoRepository
    from domain.pedido_estado import OperacaoTransicaoPedido

    db = AsyncMock()
    db.execute = AsyncMock()
    repo = PedidoRepository(db)
    repo.buscar_por_id = AsyncMock(return_value=SimpleNamespace(id=5, status="pendente"))
    repo._rastrear = AsyncMock()

    with patch("bd.repositories.pedido_repo.manager.broadcast_evento_pedido", new_callable=AsyncMock) as bc:
        await repo.atualizar_status(
            5,
            "calculado",
            OperacaoTransicaoPedido.ROTAS_CALCULAR,
            rota_id=44,
        )

    bc.assert_awaited_once()
    assert bc.await_args.args[0] == "pedido_calculado"
    assert bc.await_args.args[1]["pedido_id"] == 5
    assert bc.await_args.args[1]["rota_id"] == 44


@pytest.mark.asyncio
async def test_receber_telemetria_broadcast_inclui_pedido_id():
    from server.routers.telemetria import receber_telemetria
    from server.schemas.schemas import TelemetriaCreate

    db = MagicMock()
    drone = _drone("DP-01", status="aguardando")
    telemetria_reg = _telemetria("DP-01")
    body = TelemetriaCreate(
        drone_id="DP-01",
        latitude=-19.93,
        longitude=-43.95,
        altitude_m=50.0,
        velocidade_ms=12.0,
        bateria_pct=0.77,
        vento_ms=2.1,
        direcao_vento=180.0,
        status="em_voo",
    )

    with patch("server.routers.telemetria.TelemetriaRepository") as telemetria_repo, \
         patch("server.routers.telemetria.DroneRepository") as drone_repo, \
         patch("server.routers.telemetria.sincronizar_pedidos_apos_telemetria", new_callable=AsyncMock) as sync_pedidos, \
         patch("server.routers.telemetria.manager.broadcast_telemetria", new_callable=AsyncMock) as bc_telem, \
         patch("server.routers.telemetria.manager.broadcast_alerta", new_callable=AsyncMock), \
         patch("server.routers.telemetria.manager.broadcast_status_frota", new_callable=AsyncMock):
        telemetria_repo.return_value.criar = AsyncMock(return_value=telemetria_reg)
        drone_repo.return_value.buscar_por_id = AsyncMock(return_value=drone)
        drone_repo.return_value.atualizar_posicao_e_bateria = AsyncMock()
        drone_repo.return_value.buscar_disponiveis = AsyncMock(return_value=[drone])
        sync_pedidos.return_value = {
            "pedido_ids": [1, 2],
            "pedido_id": 1,
            "eta_seg": 180,
            "eventos": [{"evento": "pedido_em_voo", "pedido_id": 1}],
            "pedidos_ativos": [{"pedido_id": 1, "status": "em_voo"}],
        }

        await receber_telemetria(body=body, db=db, _auth=True)

    payload = bc_telem.await_args.args[1]
    assert payload["pedido_id"] == 1
    assert payload["pedido_ids"] == [1, 2]
    assert payload["pedidos_ativos"][0]["pedido_id"] == 1

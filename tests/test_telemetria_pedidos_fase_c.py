# =============================================================================
# tests/test_telemetria_pedidos_fase_c.py — Fase C (despacho / em voo via telemetria)
# =============================================================================
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.mark.asyncio
async def test_sincronizar_sem_rota_ativa():
    from server.services.telemetria_pedidos import sincronizar_pedidos_apos_telemetria

    db = MagicMock()
    with patch("server.services.telemetria_pedidos.RotaRepository") as RR:
        RR.return_value.buscar_ativa_por_drone = AsyncMock(return_value=None)
        out = await sincronizar_pedidos_apos_telemetria(
            db,
            drone_id="DP-01",
            latitude=-19.9,
            longitude=-43.9,
            velocidade_ms=8.0,
            status_payload="em_voo",
        )
    assert out == {"pedido_ids": [], "eta_seg": None, "eventos": []}


@pytest.mark.asyncio
async def test_sincronizar_despacha_e_promove_em_voo_no_mesmo_tick():
    """calculado→despachado e, com velocidade acima do limiar, despachado→em_voo."""
    from server.services.telemetria_pedidos import sincronizar_pedidos_apos_telemetria

    db = MagicMock()
    rota = SimpleNamespace(id=3, pedido_ids=[101])
    p_calc = SimpleNamespace(
        id=101,
        status="calculado",
        latitude=-19.92,
        longitude=-43.94,
    )
    p_desp = SimpleNamespace(
        id=101,
        status="despachado",
        latitude=-19.92,
        longitude=-43.94,
    )
    p_em_voo = SimpleNamespace(
        id=101,
        status="em_voo",
        latitude=-19.92,
        longitude=-43.94,
    )

    atualizar_lote = AsyncMock()
    with patch("server.services.telemetria_pedidos.RotaRepository") as RR:
        RR.return_value.buscar_ativa_por_drone = AsyncMock(return_value=rota)
        with patch("server.services.telemetria_pedidos.PedidoRepository") as PR:
            PR.return_value.buscar_por_ids = AsyncMock(
                side_effect=[[p_calc], [p_desp], [p_em_voo]]
            )
            PR.return_value.atualizar_status_lote = atualizar_lote
            with patch(
                "server.services.telemetria_pedidos.manager.broadcast_evento_pedido",
                new_callable=AsyncMock,
            ) as bc:
                await sincronizar_pedidos_apos_telemetria(
                    db,
                    drone_id="DP-01",
                    latitude=-19.91,
                    longitude=-43.93,
                    velocidade_ms=5.0,
                    status_payload="em_voo",
                )

    assert atualizar_lote.await_count == 2
    primeira = atualizar_lote.await_args_list[0].kwargs
    assert primeira["status"] == "despachado"
    assert primeira["operacao"].value == "telem_despacho"
    segunda = atualizar_lote.await_args_list[1].kwargs
    assert segunda["status"] == "em_voo"
    assert segunda["operacao"].value == "telem_em_voo"
    assert bc.await_count == 2


@pytest.mark.asyncio
async def test_sincronizar_so_despacha_sem_movimento():
    from domain.pedido_estado import OperacaoTransicaoPedido
    from server.services.telemetria_pedidos import sincronizar_pedidos_apos_telemetria

    db = MagicMock()
    rota = SimpleNamespace(id=2, pedido_ids=[55])
    p_calc = SimpleNamespace(
        id=55,
        status="calculado",
        latitude=-19.92,
        longitude=-43.94,
    )
    p_desp = SimpleNamespace(
        id=55,
        status="despachado",
        latitude=-19.92,
        longitude=-43.94,
    )

    atualizar_lote = AsyncMock()
    with patch("server.services.telemetria_pedidos.RotaRepository") as RR:
        RR.return_value.buscar_ativa_por_drone = AsyncMock(return_value=rota)
        with patch("server.services.telemetria_pedidos.PedidoRepository") as PR:
            PR.return_value.buscar_por_ids = AsyncMock(
                side_effect=[[p_calc], [p_desp]]
            )
            PR.return_value.atualizar_status_lote = atualizar_lote
            with patch(
                "server.services.telemetria_pedidos.manager.broadcast_evento_pedido",
                new_callable=AsyncMock,
            ):
                await sincronizar_pedidos_apos_telemetria(
                    db,
                    drone_id="DP-02",
                    latitude=-19.91,
                    longitude=-43.93,
                    velocidade_ms=0.5,
                    status_payload="parado",
                )

    atualizar_lote.assert_awaited_once()
    assert atualizar_lote.await_args.kwargs["operacao"] == OperacaoTransicaoPedido.TELEM_DESPACHO


@pytest.mark.asyncio
async def test_apenas_primeiro_despachado_na_ordem_vai_para_em_voo():
    from server.services.telemetria_pedidos import sincronizar_pedidos_apos_telemetria

    db = MagicMock()
    rota = SimpleNamespace(id=9, pedido_ids=[1, 2])
    p1 = SimpleNamespace(id=1, status="despachado", latitude=-19.0, longitude=-43.0)
    p2 = SimpleNamespace(id=2, status="despachado", latitude=-19.1, longitude=-43.1)

    atualizar_lote = AsyncMock()
    with patch("server.services.telemetria_pedidos.RotaRepository") as RR:
        RR.return_value.buscar_ativa_por_drone = AsyncMock(return_value=rota)
        with patch("server.services.telemetria_pedidos.PedidoRepository") as PR:
            PR.return_value.buscar_por_ids = AsyncMock(
                side_effect=[
                    [p1, p2],
                    [
                        SimpleNamespace(
                            id=1, status="em_voo", latitude=-19.0, longitude=-43.0
                        ),
                        p2,
                    ],
                ]
            )
            PR.return_value.atualizar_status_lote = atualizar_lote
            with patch(
                "server.services.telemetria_pedidos.manager.broadcast_evento_pedido",
                new_callable=AsyncMock,
            ):
                await sincronizar_pedidos_apos_telemetria(
                    db,
                    drone_id="DP-03",
                    latitude=-19.05,
                    longitude=-43.05,
                    velocidade_ms=6.0,
                    status_payload="em_voo",
                )

    atualizar_lote.assert_awaited_once()
    assert atualizar_lote.await_args.kwargs["ids"] == [1]

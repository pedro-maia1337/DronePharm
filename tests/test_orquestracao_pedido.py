# =============================================================================
# tests/test_orquestracao_pedido.py — Fase B (orquestração pós-pedido)
# =============================================================================
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.mark.asyncio
async def test_orquestracao_ignora_pedido_nao_pendente():
    from server.services.orquestracao_pedido import executar_orquestracao_novo_pedido

    session = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)

    with patch("server.services.orquestracao_pedido.AsyncSessionLocal", return_value=cm):
        with patch("server.services.orquestracao_pedido.PedidoRepository") as PR:
            PR.return_value.buscar_por_id = AsyncMock(
                return_value=SimpleNamespace(id=1, status="calculado")
            )
            with patch(
                "server.services.roteirizacao_service.calcular_rotas_para_pedidos"
            ) as calc:
                await executar_orquestracao_novo_pedido(1)
                calc.assert_not_called()


@pytest.mark.asyncio
async def test_orquestracao_sem_drone_disponivel():
    from server.services.orquestracao_pedido import executar_orquestracao_novo_pedido

    session = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)

    with patch("server.services.orquestracao_pedido.AsyncSessionLocal", return_value=cm):
        with patch("server.services.orquestracao_pedido.PedidoRepository") as PR:
            PR.return_value.buscar_por_id = AsyncMock(
                return_value=SimpleNamespace(id=1, status="pendente")
            )
            with patch("server.services.orquestracao_pedido.DroneRepository") as DR:
                DR.return_value.buscar_disponiveis = AsyncMock(return_value=[])
                with patch(
                    "server.services.roteirizacao_service.calcular_rotas_para_pedidos"
                ) as calc:
                    await executar_orquestracao_novo_pedido(1)
                    calc.assert_not_called()


@pytest.mark.asyncio
async def test_orquestracao_chama_calculo_quando_pendente_e_drone():
    from server.services.orquestracao_pedido import executar_orquestracao_novo_pedido

    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)

    drone = SimpleNamespace(id="DP-99")

    with patch("server.services.orquestracao_pedido.AsyncSessionLocal", return_value=cm):
        with patch("server.services.orquestracao_pedido.PedidoRepository") as PR:
            PR.return_value.buscar_por_id = AsyncMock(
                return_value=SimpleNamespace(id=7, status="pendente")
            )
            with patch("server.services.orquestracao_pedido.DroneRepository") as DR:
                DR.return_value.buscar_disponiveis = AsyncMock(return_value=[drone])
                with patch(
                    "server.services.roteirizacao_service.calcular_rotas_para_pedidos",
                    new_callable=AsyncMock,
                ) as calc:
                    calc.return_value = MagicMock()
                    await executar_orquestracao_novo_pedido(7)
                    calc.assert_awaited_once()
                    kwargs = calc.call_args[1]
                    assert kwargs["pedido_ids"] == [7]
                    assert kwargs["drone_id"] == "DP-99"
                    session.commit.assert_awaited_once()


class _ExcHttpLike(Exception):
    def __init__(self):
        self.status_code = 422
        self.detail = "vento"


@pytest.mark.asyncio
async def test_orquestracao_erro_http_like_faz_rollback_sem_propagar():
    from server.services.orquestracao_pedido import executar_orquestracao_novo_pedido

    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)

    drone = SimpleNamespace(id="DP-01")

    with patch("server.services.orquestracao_pedido.AsyncSessionLocal", return_value=cm):
        with patch("server.services.orquestracao_pedido.PedidoRepository") as PR:
            PR.return_value.buscar_por_id = AsyncMock(
                return_value=SimpleNamespace(id=7, status="pendente")
            )
            with patch("server.services.orquestracao_pedido.DroneRepository") as DR:
                DR.return_value.buscar_disponiveis = AsyncMock(return_value=[drone])
                with patch(
                    "server.services.roteirizacao_service.calcular_rotas_para_pedidos",
                    new_callable=AsyncMock,
                ) as calc:
                    calc.side_effect = _ExcHttpLike()
                    await executar_orquestracao_novo_pedido(7)
                    session.rollback.assert_awaited_once()
                    session.commit.assert_not_called()

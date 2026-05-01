import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _rota(status: str = "calculada"):
    return SimpleNamespace(
        id=9,
        drone_id="DP-01",
        pedido_ids=[101, 102],
        status=status,
    )


def _pedido(pedido_id: int, status: str = "calculado"):
    return SimpleNamespace(id=pedido_id, status=status)


@pytest.mark.asyncio
async def test_despachar_rota_atualiza_rota_pedidos_e_drone():
    from server.services.despacho import despachar_rota

    db = AsyncMock()
    rota = _rota()
    pedidos = [_pedido(101), _pedido(102)]

    with patch("server.services.despacho.RotaRepository") as RR, \
         patch("server.services.despacho.PedidoRepository") as PR, \
         patch("server.services.despacho.DroneRepository") as DR:
        RR.return_value.buscar_por_id = AsyncMock(return_value=rota)
        RR.return_value.atualizar_status = AsyncMock()
        PR.return_value.buscar_por_ids = AsyncMock(return_value=pedidos)
        PR.return_value.atualizar_status_lote = AsyncMock()
        DR.return_value.atualizar = AsyncMock()

        out = await despachar_rota(db, 9)

    RR.return_value.atualizar_status.assert_awaited_once_with(9, "em_execucao")
    PR.return_value.atualizar_status_lote.assert_awaited_once()
    kwargs = PR.return_value.atualizar_status_lote.await_args.kwargs
    assert kwargs["ids"] == [101, 102]
    assert kwargs["status"] == "despachado"
    assert kwargs["rota_id"] == 9
    assert kwargs["drone_id"] == "DP-01"
    DR.return_value.atualizar.assert_awaited_once_with("DP-01", status="em_voo")
    db.flush.assert_awaited_once()
    assert out["status_rota"] == "em_execucao"


@pytest.mark.asyncio
async def test_despachar_rota_inexistente_retorna_404():
    from fastapi import HTTPException
    from server.services.despacho import despachar_rota

    db = MagicMock()
    with patch("server.services.despacho.RotaRepository") as RR:
        RR.return_value.buscar_por_id = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            await despachar_rota(db, 99)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_despachar_rota_ja_em_execucao_retorna_400():
    from fastapi import HTTPException
    from server.services.despacho import despachar_rota

    db = MagicMock()
    with patch("server.services.despacho.RotaRepository") as RR:
        RR.return_value.buscar_por_id = AsyncMock(return_value=_rota(status="em_execucao"))
        with pytest.raises(HTTPException) as exc:
            await despachar_rota(db, 9)

    assert exc.value.status_code == 400

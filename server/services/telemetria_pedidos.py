# =============================================================================
# server/services/telemetria_pedidos.py
# Fase C — despacho (calculado→despachado) e confirmação em voo (despachado→em_voo)
# a partir da telemetria, com ETA aproximado para broadcast.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from algorithms.distancia import haversine
from bd.repositories.pedido_repo import PedidoRepository
from bd.repositories.rota_repo import RotaRepository
from config.settings import VELOCIDADE_CONFIRMA_EM_VOO_MS
from domain.pedido_estado import OperacaoTransicaoPedido, StatusPedido
from bd.models import Pedido as PedidoORM
from models.pedido import Coordenada
from server.websocket.connection_manager import manager
from server.services.pedido_tracking import listar_pedidos_ativos_por_ids

# Pedidos com entrega pendente (ETA no mapa / WS)
STATUS_COM_ENTREGA_PENDENTE: Tuple[str, ...] = (
    StatusPedido.DESPACHADO,
    StatusPedido.EM_VOO,
)


def _por_id(pedidos: List[PedidoORM]) -> Dict[int, PedidoORM]:
    return {p.id: p for p in pedidos}


def _primeiro_na_rota_com_status(
    rota_pedido_ids: List[int],
    por_id: Dict[int, PedidoORM],
    *statuses: str,
) -> Optional[PedidoORM]:
    for pid in rota_pedido_ids:
        p = por_id.get(pid)
        if p and p.status in statuses:
            return p
    return None


def _estimar_eta_seg(
    lat: float,
    lon: float,
    pedido_lat: float,
    pedido_lon: float,
    velocidade_ms: float,
) -> int:
    """Distância até o ponto de entrega / velocidade em solo (limite inferior)."""
    d_km = haversine(
        Coordenada(lat, lon),
        Coordenada(pedido_lat, pedido_lon),
    )
    v_kmh = max(velocidade_ms * 3.6, 5.0)
    return max(0, int((d_km / v_kmh) * 3600))


async def sincronizar_pedidos_apos_telemetria(
    db: AsyncSession,
    *,
    drone_id: str,
    latitude: float,
    longitude: float,
    velocidade_ms: float,
    status_payload: str,
) -> Dict[str, Any]:
    """
    Atualiza estados dos pedidos da rota ativa do drone e monta payload de tracking.

    Retorna dicionário com pedido_ids, pedido_id principal, eta_seg e lista de eventos.
    """
    rota_repo   = RotaRepository(db)
    pedido_repo = PedidoRepository(db)

    rota = await rota_repo.buscar_ativa_por_drone(drone_id)
    if not rota or not rota.pedido_ids:
        return {
            "pedido_ids": [],
            "eta_seg":    None,
            "eventos":    [],
        }

    pedidos = await pedido_repo.buscar_por_ids(list(rota.pedido_ids))
    if not pedidos:
        return {"pedido_ids": [], "eta_seg": None, "eventos": []}

    agora = datetime.now()
    eventos: List[Dict[str, Any]] = []

    ids_calc = [p.id for p in pedidos if p.status == StatusPedido.CALCULADO]
    if ids_calc:
        await pedido_repo.atualizar_status_lote(
            ids=ids_calc,
            status=StatusPedido.DESPACHADO,
            operacao=OperacaoTransicaoPedido.TELEM_DESPACHO,
            drone_id=drone_id,
            rota_id=rota.id,
            despachado_em=agora,
        )
        for pid in ids_calc:
            eventos.append({"evento": "pedido_despachado", "pedido_id": pid, "drone_id": drone_id})
            await manager.broadcast_evento_pedido(
                "pedido_despachado",
                {"pedido_id": pid, "drone_id": drone_id, "rota_id": rota.id},
            )
        pedidos = await pedido_repo.buscar_por_ids(list(rota.pedido_ids))

    em_movimento = (
        velocidade_ms >= VELOCIDADE_CONFIRMA_EM_VOO_MS
        or status_payload in ("em_voo", "cruzando", "entrega")
    )
    eta_seg: Optional[int] = None
    por_id = _por_id(pedidos)
    primeiro_desp = _primeiro_na_rota_com_status(
        list(rota.pedido_ids), por_id, StatusPedido.DESPACHADO
    )
    if primeiro_desp is not None and em_movimento:
        eta_seg = _estimar_eta_seg(
            latitude, longitude,
            primeiro_desp.latitude, primeiro_desp.longitude,
            velocidade_ms,
        )
        est = agora + timedelta(seconds=eta_seg or 0)
        await pedido_repo.atualizar_status_lote(
            ids=[primeiro_desp.id],
            status=StatusPedido.EM_VOO,
            operacao=OperacaoTransicaoPedido.TELEM_EM_VOO,
            drone_id=drone_id,
            rota_id=rota.id,
            estimativa_entrega_em=est,
        )
        eventos.append(
            {"evento": "pedido_em_voo", "pedido_id": primeiro_desp.id, "drone_id": drone_id}
        )
        await manager.broadcast_evento_pedido(
            "pedido_em_voo",
            {
                "pedido_id": primeiro_desp.id,
                "drone_id": drone_id,
                "rota_id": rota.id,
                "eta_seg": eta_seg,
            },
        )
        pedidos = await pedido_repo.buscar_por_ids(list(rota.pedido_ids))
        por_id = _por_id(pedidos)

    p_ids = [p.id for p in pedidos if p.status in STATUS_COM_ENTREGA_PENDENTE]
    if p_ids and eta_seg is None:
        alvo_eta = _primeiro_na_rota_com_status(
            list(rota.pedido_ids), por_id,
            StatusPedido.DESPACHADO, StatusPedido.EM_VOO,
        )
        if alvo_eta:
            eta_seg = _estimar_eta_seg(
                latitude, longitude,
                alvo_eta.latitude, alvo_eta.longitude,
                velocidade_ms,
            )

    try:
        pedidos_ativos = await listar_pedidos_ativos_por_ids(db, rota.pedido_ids)
    except Exception:
        pedidos_ativos = []
    pedido_principal = next(
        (
            item["pedido_id"]
            for item in pedidos_ativos
            if item["status"] == StatusPedido.EM_VOO
        ),
        None,
    )
    if pedido_principal is None and pedidos_ativos:
        pedido_principal = pedidos_ativos[0]["pedido_id"]

    return {
        "pedido_ids": p_ids,
        "pedido_id": pedido_principal,
        "eta_seg": eta_seg,
        "eventos": eventos,
        "pedidos_ativos": pedidos_ativos,
    }

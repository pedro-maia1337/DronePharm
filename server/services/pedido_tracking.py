from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from algorithms.distancia import haversine
from bd.repositories.drone_repo import DroneRepository
from bd.repositories.pedido_repo import PedidoRepository
from bd.repositories.rota_repo import RotaRepository
from bd.repositories.telemetria_repo import TelemetriaRepository
from domain.pedido_estado import StatusPedido
from models.pedido import Coordenada

STATUS_PEDIDOS_ATIVOS_TRACKING: Sequence[str] = (
    StatusPedido.CALCULADO,
    StatusPedido.DESPACHADO,
    StatusPedido.EM_VOO,
)


def _tempo_decorrido_seg(despachado_em: Optional[datetime], agora: datetime) -> Optional[int]:
    if despachado_em is None:
        return None
    return max(0, int((agora - despachado_em).total_seconds()))


def _tempo_restante_seg(
    estimativa_entrega_em: Optional[datetime],
    agora: datetime,
) -> Optional[int]:
    if estimativa_entrega_em is None:
        return None
    return max(0, int((estimativa_entrega_em - agora).total_seconds()))


def _eta_por_posicao(
    *,
    latitude_atual: Optional[float],
    longitude_atual: Optional[float],
    destino_latitude: float,
    destino_longitude: float,
    velocidade_ms: Optional[float],
) -> Optional[int]:
    if latitude_atual is None or longitude_atual is None:
        return None
    velocidade_ms = velocidade_ms or 0.0
    if velocidade_ms <= 0:
        return None
    distancia_km = haversine(
        Coordenada(latitude_atual, longitude_atual),
        Coordenada(destino_latitude, destino_longitude),
    )
    velocidade_kmh = max(velocidade_ms * 3.6, 5.0)
    return max(0, int((distancia_km / velocidade_kmh) * 3600))


def montar_payload_pedido_ativo(
    pedido: Any,
    *,
    rota: Optional[Any] = None,
    drone: Optional[Any] = None,
    telemetria: Optional[Any] = None,
    agora: Optional[datetime] = None,
) -> Dict[str, Any]:
    agora = agora or datetime.now()
    latitude_atual = None
    longitude_atual = None
    altitude_atual = None
    velocidade_ms = None
    posicao_atualizada_em = None

    if telemetria is not None:
        latitude_atual = telemetria.latitude
        longitude_atual = telemetria.longitude
        altitude_atual = telemetria.altitude_m
        velocidade_ms = telemetria.velocidade_ms
        posicao_atualizada_em = telemetria.criado_em
    elif drone is not None:
        latitude_atual = drone.latitude_atual
        longitude_atual = drone.longitude_atual
        velocidade_ms = getattr(drone, "velocidade_ms", None)

    tempo_restante_seg = _tempo_restante_seg(pedido.estimativa_entrega_em, agora)
    if tempo_restante_seg is None:
        tempo_restante_seg = _eta_por_posicao(
            latitude_atual=latitude_atual,
            longitude_atual=longitude_atual,
            destino_latitude=pedido.latitude,
            destino_longitude=pedido.longitude,
            velocidade_ms=velocidade_ms,
        )

    return {
        "pedido_id": pedido.id,
        "rota_id": pedido.rota_id,
        "drone_id": rota.drone_id if rota is not None else None,
        "status": pedido.status,
        "estimativa_entrega_em": pedido.estimativa_entrega_em,
        "tempo_decorrido_seg": _tempo_decorrido_seg(pedido.despachado_em, agora),
        "tempo_restante_seg": tempo_restante_seg,
        "posicao_atual": {
            "latitude": latitude_atual,
            "longitude": longitude_atual,
            "altitude_m": altitude_atual,
            "atualizado_em": posicao_atualizada_em,
        },
        "destino": {
            "latitude": pedido.latitude,
            "longitude": pedido.longitude,
        },
        "pedido": {
            "prioridade": pedido.prioridade,
            "descricao": pedido.descricao,
            "farmacia_id": pedido.farmacia_id,
            "janela_fim": pedido.janela_fim,
        },
    }


async def obter_pedido_ativo(db: AsyncSession, pedido_id: int) -> Optional[Dict[str, Any]]:
    pedido_repo = PedidoRepository(db)
    rota_repo = RotaRepository(db)
    drone_repo = DroneRepository(db)
    telemetria_repo = TelemetriaRepository(db)

    pedido = await pedido_repo.buscar_por_id(pedido_id)
    if not pedido or pedido.status not in STATUS_PEDIDOS_ATIVOS_TRACKING:
        return None

    rota = await rota_repo.buscar_por_id(pedido.rota_id) if pedido.rota_id else None
    drone = await drone_repo.buscar_por_id(rota.drone_id) if rota else None
    telemetria = await telemetria_repo.buscar_ultima(rota.drone_id) if rota else None
    return montar_payload_pedido_ativo(
        pedido,
        rota=rota,
        drone=drone,
        telemetria=telemetria,
    )


async def listar_pedidos_ativos_por_ids(
    db: AsyncSession,
    pedido_ids: Sequence[int],
) -> List[Dict[str, Any]]:
    if not pedido_ids:
        return []

    pedido_repo = PedidoRepository(db)
    rota_repo = RotaRepository(db)
    drone_repo = DroneRepository(db)
    telemetria_repo = TelemetriaRepository(db)

    pedidos = await pedido_repo.buscar_por_ids(list(pedido_ids))
    ativos = [p for p in pedidos if p.status in STATUS_PEDIDOS_ATIVOS_TRACKING]
    if not ativos:
        return []

    rota_ids = {p.rota_id for p in ativos if p.rota_id is not None}
    rotas = {
        rota_id: await rota_repo.buscar_por_id(rota_id)
        for rota_id in rota_ids
    }
    drone_ids = {rota.drone_id for rota in rotas.values() if rota is not None}
    drones = {
        drone_id: await drone_repo.buscar_por_id(drone_id)
        for drone_id in drone_ids
    }
    telemetrias = {
        drone_id: await telemetria_repo.buscar_ultima(drone_id)
        for drone_id in drone_ids
    }

    return [
        montar_payload_pedido_ativo(
            pedido,
            rota=rotas.get(pedido.rota_id),
            drone=drones.get(rotas[pedido.rota_id].drone_id) if pedido.rota_id in rotas and rotas[pedido.rota_id] else None,
            telemetria=telemetrias.get(rotas[pedido.rota_id].drone_id) if pedido.rota_id in rotas and rotas[pedido.rota_id] else None,
        )
        for pedido in ativos
    ]

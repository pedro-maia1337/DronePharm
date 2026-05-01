from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from algorithms.distancia import haversine
from bd.repositories.drone_repo import DroneRepository
from bd.repositories.pedido_repo import PedidoRepository
from bd.repositories.rota_repo import RotaRepository
from bd.repositories.telemetria_repo import TelemetriaRepository
from domain.pedido_estado import StatusPedido
from models.pedido import Coordenada

STATUS_PEDIDOS_MONITORAMENTO: Sequence[str] = (
    StatusPedido.DESPACHADO,
    StatusPedido.EM_VOO,
)
STATUS_ROTAS_MONITORAMENTO: Sequence[str] = ("calculada", "em_execucao")


def calcular_eta_segundos(
    *,
    latitude_atual: Optional[float],
    longitude_atual: Optional[float],
    destino_latitude: float,
    destino_longitude: float,
    velocidade_ms: Optional[float],
) -> Optional[int]:
    if latitude_atual is None or longitude_atual is None:
        return None
    if velocidade_ms is None or velocidade_ms <= 0:
        return None

    distancia_km = haversine(
        Coordenada(latitude_atual, longitude_atual),
        Coordenada(destino_latitude, destino_longitude),
    )
    distancia_m = distancia_km * 1000.0
    return max(0, int(distancia_m / velocidade_ms))


def montar_payload_monitoramento(
    *,
    drone_id: str,
    pedido_id: Optional[int],
    latitude: Optional[float],
    longitude: Optional[float],
    velocidade_ms: Optional[float],
    direcao: Optional[float],
    status_missao: Optional[str],
    eta_segundos: Optional[int],
) -> Dict[str, Any]:
    return {
        "drone_id": drone_id,
        "pedido_id": pedido_id,
        "posicao": {
            "lat": latitude,
            "lng": longitude,
        },
        "vetor": {
            "velocidade_ms": velocidade_ms,
            "direcao": direcao,
        },
        "status_missao": status_missao,
        "eta_segundos": eta_segundos,
    }


def _pedido_principal_na_rota(
    rota: Any,
    pedidos_por_id: Dict[int, Any],
) -> Optional[Any]:
    for status in (StatusPedido.EM_VOO, StatusPedido.DESPACHADO):
        for pedido_id in rota.pedido_ids or []:
            pedido = pedidos_por_id.get(pedido_id)
            if pedido and pedido.status == status:
                return pedido
    return None


async def listar_snapshot_monitoramento(db: AsyncSession) -> List[Dict[str, Any]]:
    rota_repo = RotaRepository(db)
    pedido_repo = PedidoRepository(db)
    drone_repo = DroneRepository(db)
    telemetria_repo = TelemetriaRepository(db)

    rotas: List[Any] = []
    for status in STATUS_ROTAS_MONITORAMENTO:
        rotas.extend(await rota_repo.listar_por_status(status))

    rotas_por_id: Dict[int, Any] = {}
    for rota in rotas:
        if rota.id not in rotas_por_id:
            rotas_por_id[rota.id] = rota

    rotas_ativas = list(rotas_por_id.values())
    if not rotas_ativas:
        return []

    pedido_ids = [
        pedido_id
        for rota in rotas_ativas
        for pedido_id in (rota.pedido_ids or [])
    ]
    if not pedido_ids:
        return []

    pedidos = await pedido_repo.buscar_por_ids(pedido_ids)
    pedidos_por_id = {
        pedido.id: pedido
        for pedido in pedidos
        if pedido.status in STATUS_PEDIDOS_MONITORAMENTO
    }
    if not pedidos_por_id:
        return []

    drone_ids = [rota.drone_id for rota in rotas_ativas]
    drones = {
        drone.id: drone
        for drone in await drone_repo.buscar_por_ids(drone_ids)
    }
    telemetrias = await telemetria_repo.buscar_ultimas_por_drones(drone_ids)

    snapshot: List[Dict[str, Any]] = []
    for rota in rotas_ativas:
        pedido = _pedido_principal_na_rota(rota, pedidos_por_id)
        if pedido is None:
            continue

        drone = drones.get(rota.drone_id)
        telemetria = telemetrias.get(rota.drone_id)

        latitude = (
            telemetria.latitude if telemetria is not None
            else getattr(drone, "latitude_atual", None)
        )
        longitude = (
            telemetria.longitude if telemetria is not None
            else getattr(drone, "longitude_atual", None)
        )
        velocidade_ms = (
            telemetria.velocidade_ms if telemetria is not None
            else getattr(drone, "velocidade_ms", None)
        )
        direcao = (
            getattr(telemetria, "direcao", None)
            if telemetria is not None
            else None
        )
        if direcao is None and telemetria is not None:
            direcao = getattr(telemetria, "direcao_vento", None)

        snapshot.append(
            montar_payload_monitoramento(
                drone_id=rota.drone_id,
                pedido_id=pedido.id,
                latitude=latitude,
                longitude=longitude,
                velocidade_ms=velocidade_ms,
                direcao=direcao,
                status_missao=pedido.status,
                eta_segundos=calcular_eta_segundos(
                    latitude_atual=latitude,
                    longitude_atual=longitude,
                    destino_latitude=pedido.latitude,
                    destino_longitude=pedido.longitude,
                    velocidade_ms=velocidade_ms,
                ),
            )
        )

    return snapshot

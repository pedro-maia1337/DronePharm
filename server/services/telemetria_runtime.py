from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from bd.repositories.drone_repo import DroneRepository
from bd.repositories.telemetria_repo import TelemetriaRepository
from config.settings import DRONE_BATERIA_MINIMA, VENTO_MAX_OPERACIONAL_MS
from server.schemas.schemas import TelemetriaResponse
from server.services.telemetria_pedidos import sincronizar_pedidos_apos_telemetria
from server.websocket.connection_manager import manager

log = logging.getLogger(__name__)


async def processar_telemetria(
    db: AsyncSession,
    *,
    drone_id: str,
    latitude: float,
    longitude: float,
    altitude_m: float,
    velocidade_ms: float,
    bateria_pct: float,
    vento_ms: float,
    direcao_vento: float,
    status: str,
    direcao: Optional[float] = None,
) -> Dict[str, Any]:
    repo = TelemetriaRepository(db)
    drone_repo = DroneRepository(db)

    drone = await drone_repo.buscar_por_id(drone_id)
    if not drone:
        raise HTTPException(status_code=404, detail=f"Drone '{drone_id}' não encontrado.")

    registro = await repo.criar(
        drone_id=drone_id,
        latitude=latitude,
        longitude=longitude,
        altitude_m=altitude_m,
        velocidade_ms=velocidade_ms,
        bateria_pct=bateria_pct,
        vento_ms=vento_ms,
        direcao_vento=direcao_vento,
        status=status,
    )

    await drone_repo.atualizar_posicao_e_bateria(
        drone_id=drone_id,
        latitude=latitude,
        longitude=longitude,
        bateria_pct=bateria_pct,
        status=status,
    )

    sync_pedidos = await sincronizar_pedidos_apos_telemetria(
        db,
        drone_id=drone_id,
        latitude=latitude,
        longitude=longitude,
        velocidade_ms=velocidade_ms,
        status_payload=status,
    )

    payload_telem = TelemetriaResponse.model_validate(registro).model_dump(mode="json")
    payload_telem.update(
        {
            "pedido_id": sync_pedidos.get("pedido_id"),
            "status_missao": sync_pedidos.get("status_missao") or status,
            "eta_segundos": sync_pedidos.get("eta_seg"),
            "direcao": direcao if direcao is not None else direcao_vento,
        }
    )
    await manager.broadcast_telemetria(drone_id, payload_telem)

    if bateria_pct <= DRONE_BATERIA_MINIMA:
        log.critical(
            "BATERIA CRITICA: drone=%s bateria=%.1f%%",
            drone_id,
            bateria_pct * 100,
        )
        await manager.broadcast_alerta(
            tipo="BATERIA_CRITICA",
            drone_id=drone_id,
            detalhe={
                "bateria_pct": bateria_pct,
                "latitude": latitude,
                "longitude": longitude,
                "mensagem": f"Bateria em {bateria_pct * 100:.1f}% - retorno imediato recomendado.",
            },
        )

    if vento_ms > VENTO_MAX_OPERACIONAL_MS:
        log.warning("VENTO EXCESSIVO: drone=%s vento=%.1f m/s", drone_id, vento_ms)
        await manager.broadcast_alerta(
            tipo="VENTO_EXCESSIVO",
            drone_id=drone_id,
            detalhe={
                "vento_ms": vento_ms,
                "limite_ms": VENTO_MAX_OPERACIONAL_MS,
                "mensagem": f"Vento em {vento_ms:.1f} m/s acima do limite operacional.",
            },
        )

    if status == "emergencia":
        await manager.broadcast_alerta(
            tipo="EMERGENCIA",
            drone_id=drone_id,
            detalhe={
                "latitude": latitude,
                "longitude": longitude,
                "mensagem": "Drone reportou status de emergencia.",
            },
        )

    disponiveis = await drone_repo.buscar_disponiveis()
    await manager.broadcast_status_frota(
        [
            {
                "id": d.id,
                "nome": d.nome,
                "status": d.status,
                "bateria_pct": d.bateria_pct,
                "latitude_atual": d.latitude_atual,
                "longitude_atual": d.longitude_atual,
            }
            for d in disponiveis
        ]
    )

    return {
        "registro": registro,
        "sync_pedidos": sync_pedidos,
        "payload": payload_telem,
    }

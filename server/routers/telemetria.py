# =============================================================================
# servidor/routers/telemetria.py
# Telemetria do drone Arduino — /api/v1/telemetria
# =============================================================================

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.schemas.schemas import TelemetriaCreate, TelemetriaResponse
from bd.database import get_db
from bd.repositories.telemetria_repo import TelemetriaRepository
from bd.repositories.drone_repo import DroneRepository
from config.settings import DRONE_BATERIA_MINIMA, VENTO_MAX_OPERACIONAL_MS

import logging
log = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/",
    response_model=TelemetriaResponse,
    status_code=201,
    summary="Receber telemetria do drone",
    description=(
        "Endpoint chamado pelo Arduino a cada 2 segundos via MAVLink/HTTP. "
        "Persiste o snapshot e aciona alertas automáticos para bateria crítica (<20%) "
        "ou vento excessivo (>12 m/s)."
    ),
)
async def receber_telemetria(
    body: TelemetriaCreate,
    db:   AsyncSession = Depends(get_db),
):
    repo       = TelemetriaRepository(db)
    drone_repo = DroneRepository(db)

    # Valida drone
    drone = await drone_repo.buscar_por_id(body.drone_id)
    if not drone:
        raise HTTPException(status_code=404, detail=f"Drone '{body.drone_id}' não encontrado.")

    # Persiste snapshot
    registro = await repo.criar(
        drone_id=body.drone_id,
        latitude=body.latitude,
        longitude=body.longitude,
        altitude_m=body.altitude_m,
        velocidade_ms=body.velocidade_ms,
        bateria_pct=body.bateria_pct,
        vento_ms=body.vento_ms,
        direcao_vento=body.direcao_vento,
        status=body.status,
    )

    # Sincroniza posição e bateria do drone
    await drone_repo.atualizar_posicao_e_bateria(
        drone_id=body.drone_id,
        latitude=body.latitude,
        longitude=body.longitude,
        bateria_pct=body.bateria_pct,
        status=body.status,
    )

    # Alertas
    if body.bateria_pct <= DRONE_BATERIA_MINIMA:
        log.critical(
            f"BATERIA CRÍTICA: drone={body.drone_id} "
            f"bateria={body.bateria_pct*100:.1f}% (limiar={DRONE_BATERIA_MINIMA*100:.0f}%)"
        )

    if body.vento_ms > VENTO_MAX_OPERACIONAL_MS:
        log.warning(
            f"VENTO EXCESSIVO: drone={body.drone_id} "
            f"vento={body.vento_ms:.1f} m/s (máx={VENTO_MAX_OPERACIONAL_MS} m/s)"
        )

    return registro


@router.get(
    "/{drone_id}/ultima",
    response_model=TelemetriaResponse,
    summary="Última telemetria de um drone",
    description="Retorna o snapshot mais recente recebido do drone.",
)
async def ultima_telemetria(drone_id: str, db: AsyncSession = Depends(get_db)):
    repo     = TelemetriaRepository(db)
    registro = await repo.buscar_ultima(drone_id)
    if not registro:
        raise HTTPException(
            status_code=404,
            detail=f"Sem telemetria registrada para drone '{drone_id}'.",
        )
    return registro


@router.get(
    "/{drone_id}/historico",
    summary="Histórico de telemetria",
    description="Retorna os últimos N snapshots de telemetria do drone, do mais recente ao mais antigo.",
)
async def historico_telemetria(
    drone_id: str,
    limite:   int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    repo      = TelemetriaRepository(db)
    registros = await repo.historico(drone_id, limite)
    return {"drone_id": drone_id, "total": len(registros), "registros": registros}


@router.get(
    "/{drone_id}/posicao",
    summary="Posição atual do drone",
    description="Retorna a última posição GPS conhecida do drone.",
)
async def posicao_drone(drone_id: str, db: AsyncSession = Depends(get_db)):
    repo     = TelemetriaRepository(db)
    registro = await repo.buscar_ultima(drone_id)
    if not registro:
        raise HTTPException(
            status_code=404,
            detail=f"Sem dados de posição para drone '{drone_id}'.",
        )
    return {
        "drone_id":    drone_id,
        "latitude":    registro.latitude,
        "longitude":   registro.longitude,
        "altitude_m":  registro.altitude_m,
        "bateria_pct": registro.bateria_pct,
        "status":      registro.status,
        "atualizado_em": registro.criado_em,
    }
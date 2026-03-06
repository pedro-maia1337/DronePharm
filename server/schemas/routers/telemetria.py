# =============================================================================
# servidor/routers/telemetria.py
# Telemetria recebida do drone Arduino via POST /api/v1/telemetria
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


@router.post("/", response_model=TelemetriaResponse, status_code=201,
             summary="Receber telemetria do drone")
async def receber_telemetria(
    body: TelemetriaCreate,
    db:   AsyncSession = Depends(get_db),
):
    """
    Endpoint chamado pelo Arduino (ou pelo monitor Python) a cada ciclo de telemetria.

    Persiste os dados e dispara alertas automáticos se:
    - Bateria ≤ 20% (DRONE_BATERIA_MINIMA)
    - Vento > 12 m/s (VENTO_MAX_OPERACIONAL_MS)
    """
    repo       = TelemetriaRepository(db)
    drone_repo = DroneRepository(db)

    # Persiste telemetria
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

    # Atualiza posição e bateria do drone no banco
    await drone_repo.atualizar_posicao_e_bateria(
        drone_id=body.drone_id,
        latitude=body.latitude,
        longitude=body.longitude,
        bateria_pct=body.bateria_pct,
        status=body.status,
    )

    # Alertas automáticos (log + resposta)
    alertas = []
    if body.bateria_pct <= DRONE_BATERIA_MINIMA:
        msg = f"ALERTA: Bateria crítica {body.bateria_pct*100:.1f}% — drone {body.drone_id}"
        log.critical(msg)
        alertas.append({"tipo": "BATERIA_CRITICA", "mensagem": msg})

    if body.vento_ms > VENTO_MAX_OPERACIONAL_MS:
        msg = f"ALERTA: Vento {body.vento_ms:.1f} m/s excede limite — drone {body.drone_id}"
        log.warning(msg)
        alertas.append({"tipo": "VENTO_EXCESSIVO", "mensagem": msg})

    if alertas:
        log.warning(f"{len(alertas)} alertas gerados para drone {body.drone_id}")

    return registro


@router.get("/{drone_id}/ultima", response_model=TelemetriaResponse,
            summary="Última telemetria de um drone")
async def ultima_telemetria(drone_id: str, db: AsyncSession = Depends(get_db)):
    repo     = TelemetriaRepository(db)
    registro = await repo.buscar_ultima(drone_id)
    if not registro:
        raise HTTPException(status_code=404,
                            detail=f"Sem telemetria registrada para drone '{drone_id}'.")
    return registro


@router.get("/{drone_id}/historico", summary="Histórico de telemetria de um drone")
async def historico_telemetria(
    drone_id: str,
    limite:   int = Query(100, le=1000),
    db:       AsyncSession = Depends(get_db),
):
    repo      = TelemetriaRepository(db)
    registros = await repo.historico(drone_id, limite)
    return {"drone_id": drone_id, "total": len(registros), "registros": registros}

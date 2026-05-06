# =============================================================================
# servidor/routers/telemetria.py
# Telemetria do drone - /api/v1/telemetria
# Integrado com WebSocket: cada POST faz broadcast em tempo real
# =============================================================================

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from bd.database import get_db
from bd.repositories.telemetria_repo import TelemetriaRepository
from server.schemas.schemas import TelemetriaCreate, TelemetriaResponse
from server.security.rest_auth import require_rest_ingest
from server.services.telemetria_runtime import processar_telemetria

router = APIRouter()


@router.post(
    "/",
    response_model=TelemetriaResponse,
    status_code=201,
    summary="Receber telemetria do drone",
    description=(
        "Endpoint chamado pelo Arduino a cada 2 segundos via HTTP. "
        "Persiste o snapshot, aciona alertas automaticos e faz broadcast WebSocket "
        "para clientes conectados em `/ws/telemetria` e `/ws/telemetria/{drone_id}`."
    ),
)
async def receber_telemetria(
    body: TelemetriaCreate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_rest_ingest),
):
    resultado = await processar_telemetria(
        db,
        drone_id=body.drone_id,
        latitude=body.latitude,
        longitude=body.longitude,
        altitude_m=body.altitude_m,
        velocidade_ms=body.velocidade_ms,
        bateria_pct=body.bateria_pct,
        vento_ms=body.vento_ms,
        direcao_vento=body.direcao_vento,
        status=body.status,
        direcao=body.direcao,
    )
    return resultado["registro"]


@router.get(
    "/{drone_id}/ultima",
    response_model=TelemetriaResponse,
    summary="Ultima telemetria de um drone",
)
async def ultima_telemetria(drone_id: str, db: AsyncSession = Depends(get_db)):
    repo = TelemetriaRepository(db)
    registro = await repo.buscar_ultima(drone_id)
    if not registro:
        raise HTTPException(
            status_code=404,
            detail=f"Sem telemetria registrada para drone '{drone_id}'.",
        )
    return registro


@router.get(
    "/{drone_id}/historico",
    summary="Historico de telemetria",
    description="Retorna os ultimos N snapshots de telemetria, do mais recente ao mais antigo.",
)
async def historico_telemetria(
    drone_id: str,
    limite: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    repo = TelemetriaRepository(db)
    registros = await repo.historico(drone_id, limite)
    return {"drone_id": drone_id, "total": len(registros), "registros": registros}


@router.get(
    "/{drone_id}/posicao",
    summary="Posicao atual do drone",
)
async def posicao_drone(drone_id: str, db: AsyncSession = Depends(get_db)):
    repo = TelemetriaRepository(db)
    registro = await repo.buscar_ultima(drone_id)
    if not registro:
        raise HTTPException(
            status_code=404,
            detail=f"Sem dados de posicao para drone '{drone_id}'.",
        )
    return {
        "drone_id": drone_id,
        "latitude": registro.latitude,
        "longitude": registro.longitude,
        "altitude_m": registro.altitude_m,
        "bateria_pct": registro.bateria_pct,
        "status": registro.status,
        "atualizado_em": registro.criado_em,
    }

# =============================================================================
# servidor/routers/telemetria.py
# Telemetria do drone — /api/v1/telemetria
# Integrado com WebSocket: cada POST faz broadcast em tempo real
# =============================================================================

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.schemas.schemas import TelemetriaCreate, TelemetriaResponse
from bd.database import get_db
from bd.repositories.telemetria_repo import TelemetriaRepository
from bd.repositories.drone_repo import DroneRepository
from config.settings import DRONE_BATERIA_MINIMA, VENTO_MAX_OPERACIONAL_MS
from server.websocket.connection_manager import manager
from server.security.rest_auth import require_rest_ingest
from server.services.telemetria_pedidos import sincronizar_pedidos_apos_telemetria

log = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/",
    response_model=TelemetriaResponse,
    status_code=201,
    summary="Receber telemetria do drone",
    description=(
        "Endpoint chamado pelo Arduino a cada 2 segundos via HTTP. "
        "Persiste o snapshot, aciona alertas automáticos e faz **broadcast WebSocket** "
        "para todos os clientes conectados em `/ws/telemetria` e `/ws/telemetria/{drone_id}`."
    ),
)
async def receber_telemetria(
    body: TelemetriaCreate,
    db:   AsyncSession = Depends(get_db),
    _auth=Depends(require_rest_ingest),
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

    # Sincroniza posição e bateria no cadastro do drone
    await drone_repo.atualizar_posicao_e_bateria(
        drone_id=body.drone_id,
        latitude=body.latitude,
        longitude=body.longitude,
        bateria_pct=body.bateria_pct,
        status=body.status,
    )

    sync_pedidos = await sincronizar_pedidos_apos_telemetria(
        db,
        drone_id=body.drone_id,
        latitude=body.latitude,
        longitude=body.longitude,
        velocidade_ms=body.velocidade_ms,
        status_payload=body.status,
    )

    # ── Broadcast WebSocket — telemetria ──────────────────────────────────
    payload_telem = {
        "tipo":          "telemetria",
        "drone_id":      body.drone_id,
        "pedido_id":     sync_pedidos.get("pedido_id"),
        "latitude":      body.latitude,
        "longitude":     body.longitude,
        "altitude_m":    body.altitude_m,
        "velocidade_ms": body.velocidade_ms,
        "bateria_pct":   body.bateria_pct,
        "vento_ms":      body.vento_ms,
        "direcao_vento": body.direcao_vento,
        "status":        body.status,
        "snapshot_id":   registro.id,
        "pedido_ids":    sync_pedidos["pedido_ids"],
        "eta_seg":       sync_pedidos["eta_seg"],
        "pedidos_ativos": sync_pedidos.get("pedidos_ativos", []),
        "pedido_eventos": sync_pedidos["eventos"],
    }
    await manager.broadcast_telemetria(body.drone_id, payload_telem)

    # ── Broadcast WebSocket — alertas críticos ────────────────────────────
    if body.bateria_pct <= DRONE_BATERIA_MINIMA:
        log.critical(
            f"BATERIA CRÍTICA: drone={body.drone_id} "
            f"bateria={body.bateria_pct*100:.1f}%"
        )
        await manager.broadcast_alerta(
            tipo="BATERIA_CRITICA",
            drone_id=body.drone_id,
            detalhe={
                "bateria_pct": body.bateria_pct,
                "latitude":    body.latitude,
                "longitude":   body.longitude,
                "mensagem":    f"Bateria em {body.bateria_pct*100:.1f}% — retorno imediato recomendado.",
            },
        )

    if body.vento_ms > VENTO_MAX_OPERACIONAL_MS:
        log.warning(
            f"VENTO EXCESSIVO: drone={body.drone_id} "
            f"vento={body.vento_ms:.1f} m/s"
        )
        await manager.broadcast_alerta(
            tipo="VENTO_EXCESSIVO",
            drone_id=body.drone_id,
            detalhe={
                "vento_ms":  body.vento_ms,
                "limite_ms": VENTO_MAX_OPERACIONAL_MS,
                "mensagem":  f"Vento em {body.vento_ms:.1f} m/s acima do limite operacional.",
            },
        )

    if body.status == "emergencia":
        await manager.broadcast_alerta(
            tipo="EMERGENCIA",
            drone_id=body.drone_id,
            detalhe={
                "latitude":  body.latitude,
                "longitude": body.longitude,
                "mensagem":  "Drone reportou status de emergência.",
            },
        )

    # ── Broadcast snapshot da frota (atualiza painel) ─────────────────────
    disponiveis = await drone_repo.buscar_disponiveis()
    await manager.broadcast_status_frota([
        {
            "id":            d.id,
            "nome":          d.nome,
            "status":        d.status,
            "bateria_pct":   d.bateria_pct,
            "latitude_atual":  d.latitude_atual,
            "longitude_atual": d.longitude_atual,
        }
        for d in disponiveis
    ])

    return registro


@router.get(
    "/{drone_id}/ultima",
    response_model=TelemetriaResponse,
    summary="Última telemetria de um drone",
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
    description="Retorna os últimos N snapshots de telemetria, do mais recente ao mais antigo.",
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
        "drone_id":      drone_id,
        "latitude":      registro.latitude,
        "longitude":     registro.longitude,
        "altitude_m":    registro.altitude_m,
        "bateria_pct":   registro.bateria_pct,
        "status":        registro.status,
        "atualizado_em": registro.criado_em,
    }

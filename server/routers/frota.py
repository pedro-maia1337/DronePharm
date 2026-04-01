# =============================================================================
# server/routers/frota.py
# Gestão de frota e monitoramento de bateria/carga — /api/v1/frota
# =============================================================================

import logging
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from bd.database import get_db
from bd.models import Telemetria
from bd.repositories.drone_repo import DroneRepository
from bd.repositories.telemetria_repo import TelemetriaRepository
from bd.repositories.historico_repo import HistoricoRepository
from config.settings import DRONE_BATERIA_MINIMA
from server.websocket.connection_manager import manager
from server.security.rest_auth import require_rest_admin

log = logging.getLogger(__name__)
router = APIRouter()


# =============================================================================
# STATUS DA FROTA
# =============================================================================

@router.get(
    "/status",
    summary="Snapshot completo da frota",
    description=(
        "Retorna o estado atual de todos os drones: status, bateria, posição, "
        "missões realizadas e última telemetria recebida."
    ),
)
async def status_frota(db: AsyncSession = Depends(get_db)):
    drone_repo = DroneRepository(db)
    drones     = await drone_repo.listar()

    if not drones:
        return {"resumo": {}, "drones": []}

    # Busca a última telemetria de todos os drones em uma única query,
    # evitando o problema N+1 que ocorria com um SELECT por drone.
    drone_ids = [d.id for d in drones]
    result = await db.execute(
        select(
            Telemetria.drone_id,
            Telemetria.latitude,
            Telemetria.longitude,
            Telemetria.criado_em,
        )
        .where(Telemetria.drone_id.in_(drone_ids))
        .distinct(Telemetria.drone_id)
        .order_by(Telemetria.drone_id, Telemetria.criado_em.desc())
    )
    ultimas = {row["drone_id"]: row for row in result.mappings().all()}

    frota = []
    for d in drones:
        ultima = ultimas.get(d.id)
        frota.append({
            "id":                 d.id,
            "nome":               d.nome,
            "status":             d.status,
            "bateria_pct":        round(d.bateria_pct * 100, 1),
            "capacidade_max_kg":  d.capacidade_max_kg,
            "autonomia_max_km":   d.autonomia_max_km,
            "missoes_realizadas": d.missoes_realizadas,
            "latitude_atual":     d.latitude_atual,
            "longitude_atual":    d.longitude_atual,
            "alerta_bateria":     d.bateria_pct <= DRONE_BATERIA_MINIMA,
            "ultima_telem_em":    ultima["criado_em"].isoformat() if ultima else None,
        })

    resumo = {
        "total":          len(drones),
        "aguardando":     sum(1 for d in drones if d.status == "aguardando"),
        "em_voo":         sum(1 for d in drones if d.status == "em_voo"),
        "carregando":     sum(1 for d in drones if d.status == "carregando"),
        "manutencao":     sum(1 for d in drones if d.status == "manutencao"),
        "alerta_bateria": sum(1 for d in drones if d.bateria_pct <= DRONE_BATERIA_MINIMA),
    }

    return {"resumo": resumo, "drones": frota}


# =============================================================================
# RANKING DE BATERIA
# =============================================================================

@router.get(
    "/bateria",
    summary="Ranking de bateria da frota",
    description="Lista todos os drones ordenados pelo nível de bateria (maior primeiro).",
)
async def ranking_bateria(db: AsyncSession = Depends(get_db)):
    drone_repo   = DroneRepository(db)
    drones       = await drone_repo.listar()
    drones_sorted = sorted(drones, key=lambda d: d.bateria_pct, reverse=True)

    return {
        "total": len(drones_sorted),
        "drones": [
            {
                "id":                    d.id,
                "nome":                  d.nome,
                "status":                d.status,
                "bateria_pct":           round(d.bateria_pct * 100, 1),
                "autonomia_restante_km": round(d.autonomia_max_km * d.bateria_pct, 2),
                "alerta":                d.bateria_pct <= DRONE_BATERIA_MINIMA,
            }
            for d in drones_sorted
        ],
    }


# =============================================================================
# ALERTA DE BATERIA
# =============================================================================

@router.get(
    "/alerta-bateria",
    summary="Drones com bateria crítica",
    description="Retorna drones com bateria abaixo ou igual ao limiar mínimo operacional.",
)
async def alerta_bateria(
    limiar: float = Query(
        None,
        ge=0.0, le=1.0,
        description="Limiar customizado (0.0–1.0). Padrão: configuração do sistema.",
    ),
    db: AsyncSession = Depends(get_db),
):
    drone_repo = DroneRepository(db)
    telem_repo = TelemetriaRepository(db)
    threshold  = limiar if limiar is not None else DRONE_BATERIA_MINIMA

    drones  = await drone_repo.listar()
    criticos = [d for d in drones if d.bateria_pct <= threshold]

    resultado = []
    for d in criticos:
        ultima = await telem_repo.buscar_ultima(d.id)
        resultado.append({
            "id":          d.id,
            "nome":        d.nome,
            "status":      d.status,
            "bateria_pct": round(d.bateria_pct * 100, 1),
            "latitude":    ultima.latitude  if ultima else d.latitude_atual,
            "longitude":   ultima.longitude if ultima else d.longitude_atual,
            "ultima_telem": ultima.criado_em.isoformat() if ultima else None,
            "recomendacao": "RETORNO_IMEDIATO" if d.bateria_pct < 0.10 else "RECARREGAR_EM_BREVE",
        })

    return {
        "limiar_pct":     round(threshold * 100, 1),
        "total_criticos": len(resultado),
        "drones":         resultado,
    }


# =============================================================================
# RESUMO DE UM DRONE
# =============================================================================

@router.get(
    "/{drone_id}/resumo",
    summary="Métricas consolidadas de um drone",
    description=(
        "Retorna histórico de missões, consumo estimado, bateria atual "
        "e últimas 5 telemetrias do drone."
    ),
)
async def resumo_drone(drone_id: str, db: AsyncSession = Depends(get_db)):
    drone_repo = DroneRepository(db)
    telem_repo = TelemetriaRepository(db)

    drone = await drone_repo.buscar_por_id(drone_id)
    if not drone:
        raise HTTPException(status_code=404, detail=f"Drone '{drone_id}' não encontrado.")

    ultimas_telem = await telem_repo.historico(drone_id, limite=5)

    try:
        result = await db.execute(
            text(
                "SELECT COALESCE(SUM(distancia_km), 0) AS dist_total, "
                "       COUNT(*) AS total_missoes "
                "FROM historico_entregas WHERE drone_id = :did"
            ),
            {"did": drone_id},
        )
        row           = result.mappings().fetchone()
        dist_total    = float(row["dist_total"])   if row else 0.0
        total_missoes = int(row["total_missoes"])   if row else 0
    except Exception:
        dist_total    = 0.0
        total_missoes = drone.missoes_realizadas

    return {
        "drone": {
            "id":                drone.id,
            "nome":              drone.nome,
            "status":            drone.status,
            "bateria_pct":       round(drone.bateria_pct * 100, 1),
            "capacidade_max_kg": drone.capacidade_max_kg,
            "autonomia_max_km":  drone.autonomia_max_km,
            "velocidade_ms":     drone.velocidade_ms,
        },
        "historico": {
            "missoes_realizadas":  drone.missoes_realizadas,
            "total_no_historico":  total_missoes,
            "distancia_total_km":  round(dist_total, 2),
            "consumo_estimado_wh": round(dist_total * 15.0, 1),
        },
        "ultimas_telemetrias": [
            {
                "latitude":      t.latitude,
                "longitude":     t.longitude,
                "altitude_m":    t.altitude_m,
                "bateria_pct":   round(t.bateria_pct * 100, 1),
                "velocidade_ms": t.velocidade_ms,
                "vento_ms":      t.vento_ms,
                "status":        t.status,
                "criado_em":     t.criado_em.isoformat(),
            }
            for t in ultimas_telem
        ],
    }


# =============================================================================
# AÇÕES OPERACIONAIS
# =============================================================================

@router.post(
    "/{drone_id}/retornar",
    summary="Acionar retorno de emergência",
)
async def acionar_retorno(
    drone_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_rest_admin),
):
    drone_repo = DroneRepository(db)
    drone = await drone_repo.buscar_por_id(drone_id)
    if not drone:
        raise HTTPException(status_code=404, detail=f"Drone '{drone_id}' não encontrado.")

    await drone_repo.atualizar(drone_id, status="retornando")
    await manager.broadcast_alerta(
        tipo="RETORNO_ACIONADO",
        drone_id=drone_id,
        detalhe={
            "bateria_pct": drone.bateria_pct,
            "mensagem":    f"Retorno de emergência acionado para {drone.nome}.",
        },
    )
    return {
        "drone_id": drone_id,
        "status":   "retornando",
        "mensagem": f"Retorno de emergência acionado para {drone.nome}.",
    }


@router.post(
    "/{drone_id}/manutencao",
    summary="Colocar drone em manutenção",
)
async def colocar_em_manutencao(
    drone_id: str,
    motivo: str = Query("Manutenção programada"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_rest_admin),
):
    drone_repo = DroneRepository(db)
    drone = await drone_repo.buscar_por_id(drone_id)
    if not drone:
        raise HTTPException(status_code=404, detail=f"Drone '{drone_id}' não encontrado.")
    if drone.status == "em_voo":
        raise HTTPException(
            status_code=409,
            detail="Não é possível colocar em manutenção um drone em voo. Acione retorno primeiro.",
        )

    await drone_repo.atualizar(drone_id, status="manutencao")
    log.warning(f"Drone {drone_id} em manutenção. Motivo: {motivo}")
    return {
        "drone_id": drone_id,
        "status":   "manutencao",
        "motivo":   motivo,
        "mensagem": f"{drone.nome} colocado em manutenção.",
    }


@router.post(
    "/{drone_id}/reativar",
    summary="Reativar drone",
    description="Retorna o drone ao status 'aguardando' após manutenção ou recarga.",
)
async def reativar_drone(
    drone_id:    str,
    bateria_pct: float = Query(1.0, ge=0.0, le=1.0, description="Nível de bateria após recarga"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_rest_admin),
):
    drone_repo = DroneRepository(db)
    drone = await drone_repo.buscar_por_id(drone_id)
    if not drone:
        raise HTTPException(status_code=404, detail=f"Drone '{drone_id}' não encontrado.")

    await drone_repo.atualizar(drone_id, status="aguardando", bateria_pct=bateria_pct)
    log.info(f"Drone {drone_id} reativado. Bateria: {bateria_pct*100:.0f}%")
    return {
        "drone_id":    drone_id,
        "status":      "aguardando",
        "bateria_pct": round(bateria_pct * 100, 1),
        "mensagem":    f"{drone.nome} reativado e disponível para voo.",
    }

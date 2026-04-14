# =============================================================================
# server/routers/rotas.py
# Roteirização e gestão de rotas — /api/v1/rotas
# =============================================================================

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.schemas.schemas import (
    RoteirizarRequest, RoteirizarResponse,
    RotaResponse, RotaAbortarRequest, WaypointResponse,
)
from bd.database import get_db
from bd.repositories.pedido_repo import PedidoRepository
from bd.repositories.drone_repo import DroneRepository
from bd.repositories.rota_repo import RotaRepository
from bd.repositories.historico_repo import HistoricoRepository

from server.security.rest_auth import require_rest_admin, require_rest_write
from domain.pedido_estado import OperacaoTransicaoPedido, StatusPedido
from server.services.roteirizacao_service import calcular_rotas_para_pedidos

import logging
log = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# HELPER — converte ORM Rota → RotaResponse
# =============================================================================

def _rota_orm_para_response(rota) -> RotaResponse:
    waypoints = []
    for wp in (rota.waypoints_json or []):
        waypoints.append(WaypointResponse(
            seq=wp.get("seq", 0),
            latitude=wp.get("latitude", 0.0),
            longitude=wp.get("longitude", 0.0),
            altitude=wp.get("altitude", 50.0),
            label=wp.get("label", ""),
        ))
    return RotaResponse(
        id=rota.id,
        drone_id=rota.drone_id,
        pedido_ids=rota.pedido_ids or [],
        waypoints=waypoints,
        distancia_km=rota.distancia_km,
        tempo_min=rota.tempo_min,
        energia_wh=rota.energia_wh,
        carga_kg=rota.carga_kg,
        custo=rota.custo,
        viavel=rota.viavel,
        geracoes_ga=rota.geracoes_ga,
        status=rota.status,
        criada_em=rota.criada_em,
        concluida_em=rota.concluida_em,
    )


# =============================================================================
# CALCULAR ROTAS
# =============================================================================

@router.post(
    "/calcular",
    response_model=RoteirizarResponse,
    summary="Calcular rotas otimizadas (Clarke-Wright + GA)",
    description=(
        "Executa o pipeline completo de roteirização: "
        "Clarke-Wright Savings (fase 1) → Algoritmo Genético (fase 2). "
        "Persiste as rotas no banco e atualiza o status dos pedidos para `calculado`. "
        "Consulta automaticamente OpenWeatherMap para dados de vento."
    ),
)
async def calcular_rotas(
    body: RoteirizarRequest,
    db:   AsyncSession = Depends(get_db),
    _auth=Depends(require_rest_write),
):
    return await calcular_rotas_para_pedidos(
        db,
        pedido_ids=body.pedido_ids,
        drone_id=body.drone_id,
        forcar_recalc=body.forcar_recalc,
        vento_ms=body.vento_ms,
    )


# =============================================================================
# HISTÓRICO
# =============================================================================

@router.get(
    "/historico",
    summary="Histórico de rotas",
    description="Retorna as rotas mais recentes. Filtre por drone com `drone_id`.",
)
async def listar_historico(
    limite:   int           = Query(50, ge=1, le=500),
    drone_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    rota_repo = RotaRepository(db)
    rotas     = await rota_repo.listar_recentes(limite=limite, drone_id=drone_id)
    return {"total": len(rotas), "rotas": [_rota_orm_para_response(r) for r in rotas]}


@router.get(
    "/em-execucao",
    summary="Rotas atualmente em execução",
)
async def rotas_em_execucao(db: AsyncSession = Depends(get_db)):
    rota_repo = RotaRepository(db)
    rotas     = await rota_repo.listar_por_status("em_execucao")
    return {"total": len(rotas), "rotas": [_rota_orm_para_response(r) for r in rotas]}


# =============================================================================
# ROTA POR ID
# =============================================================================

@router.get(
    "/{rota_id}",
    response_model=RotaResponse,
    summary="Buscar rota por ID",
)
async def buscar_rota(rota_id: int, db: AsyncSession = Depends(get_db)):
    rota_repo = RotaRepository(db)
    rota      = await rota_repo.buscar_por_id(rota_id)
    if not rota:
        raise HTTPException(status_code=404, detail=f"Rota {rota_id} não encontrada.")
    return _rota_orm_para_response(rota)


# =============================================================================
# CONCLUIR ROTA
# =============================================================================

@router.patch(
    "/{rota_id}/concluir",
    summary="Marcar rota como concluída",
    description=(
        "Finaliza a rota, marca todos os pedidos como entregues "
        "e registra o histórico de entregas para KPIs."
    ),
)
async def concluir_rota(
    rota_id: int,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_rest_write),
):
    rota_repo      = RotaRepository(db)
    pedido_repo    = PedidoRepository(db)
    drone_repo     = DroneRepository(db)
    historico_repo = HistoricoRepository(db)

    rota = await rota_repo.buscar_por_id(rota_id)
    if not rota:
        raise HTTPException(status_code=404, detail=f"Rota {rota_id} não encontrada.")
    if rota.status == "concluida":
        raise HTTPException(status_code=409, detail="Rota já está concluída.")
    if rota.status == "abortada":
        raise HTTPException(status_code=409, detail="Rota foi abortada e não pode ser concluída.")

    await rota_repo.atualizar_status(rota_id, "concluida")

    pedido_ids = rota.pedido_ids or []
    await pedido_repo.atualizar_status_lote(
        ids=pedido_ids,
        status=StatusPedido.ENTREGUE,
        operacao=OperacaoTransicaoPedido.ROTAS_CONCLUIR,
    )

    pedidos = await pedido_repo.buscar_por_ids(pedido_ids)
    dist_por_pedido = rota.distancia_km / max(len(pedidos), 1)
    for pedido in pedidos:
        janela_ok = True
        if pedido.janela_fim:
            janela_ok = datetime.now() <= pedido.janela_fim
        await historico_repo.criar(
            pedido_id=pedido.id,
            rota_id=rota_id,
            drone_id=rota.drone_id,
            farmacia_id=pedido.farmacia_id,
            prioridade=pedido.prioridade,
            peso_kg=pedido.peso_kg,
            distancia_km=dist_por_pedido,
            tempo_real_min=rota.tempo_min,
            entregue_no_prazo=janela_ok,
        )

    await drone_repo.incrementar_missoes(rota.drone_id)

    return {
        "mensagem": f"Rota {rota_id} concluída. {len(pedido_ids)} entrega(s) registrada(s).",
        "rota_id": rota_id,
        "pedidos_entregues": pedido_ids,
    }


# =============================================================================
# ABORTAR ROTA
# =============================================================================

@router.patch(
    "/{rota_id}/abortar",
    summary="Abortar rota em execução",
    description="Cancela a rota e retorna os pedidos ao status 'pendente'.",
)
async def abortar_rota(
    rota_id: int,
    body: RotaAbortarRequest = RotaAbortarRequest(),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_rest_admin),
):
    rota_repo   = RotaRepository(db)
    pedido_repo = PedidoRepository(db)
    drone_repo  = DroneRepository(db)

    rota = await rota_repo.buscar_por_id(rota_id)
    if not rota:
        raise HTTPException(status_code=404, detail=f"Rota {rota_id} não encontrada.")
    if rota.status == "concluida":
        raise HTTPException(status_code=409, detail="Não é possível abortar uma rota concluída.")

    await rota_repo.atualizar_status(rota_id, "abortada")

    pedido_ids = rota.pedido_ids or []
    await pedido_repo.atualizar_status_lote(
        ids=pedido_ids,
        status=StatusPedido.PENDENTE,
        operacao=OperacaoTransicaoPedido.ROTAS_ABORTAR,
        rota_id=None,
    )
    await drone_repo.atualizar(rota.drone_id, status="aguardando")

    motivo = body.motivo or "Não informado"
    log.warning(f"Rota {rota_id} abortada. Motivo: {motivo}")

    return {
        "mensagem": f"Rota {rota_id} abortada. Pedidos devolvidos à fila.",
        "rota_id": rota_id,
        "pedidos_liberados": pedido_ids,
        "motivo": motivo,
    }

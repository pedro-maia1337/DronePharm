# =============================================================================
# servidor/routers/historico.py
# Histórico de entregas e KPIs — /api/v1/historico
# =============================================================================

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Query, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.schemas.schemas import (
    HistoricoResponse, KpiGeralResponse, KpiFarmaciaResponse, KpiTempoRealResponse
)
from bd.models import Pedido
from bd.database import get_db
from bd.repositories.historico_repo import HistoricoRepository
from domain.pedido_estado import STATUS_ATIVOS_MAPA, StatusPedido

router = APIRouter()


@router.get(
    "/",
    summary="Listar histórico de entregas",
    description="Retorna o registro consolidado de todas as entregas realizadas.",
)
async def listar_historico(
    drone_id:    Optional[str] = Query(None),
    farmacia_id: Optional[int] = Query(None),
    limite:      int           = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    repo      = HistoricoRepository(db)
    registros = await repo.listar(drone_id=drone_id, farmacia_id=farmacia_id, limite=limite)
    return {"total": len(registros), "historico": registros}


@router.get(
    "/kpis",
    response_model=KpiGeralResponse,
    summary="KPIs gerais do sistema",
    description=(
        "Retorna métricas consolidadas de todo o sistema: "
        "total de entregas, taxa de pontualidade, tempo médio e peso entregue."
    ),
)
async def kpis_gerais(db: AsyncSession = Depends(get_db)):
    repo = HistoricoRepository(db)
    dados = await repo.kpis_gerais()
    return KpiGeralResponse(
        total_entregas=int(dados.get("total_entregas") or 0),
        entregas_no_prazo=int(dados.get("entregas_no_prazo") or 0),
        taxa_pontualidade_pct=float(dados.get("taxa_pontualidade_pct") or 0.0),
        tempo_medio_min=float(dados.get("tempo_medio_min") or 0.0),
        distancia_media_km=float(dados.get("distancia_media_km") or 0.0),
        peso_total_entregue_kg=float(dados.get("peso_total_entregue_kg") or 0.0),
    )


@router.get(
    "/kpis/farmacias",
    summary="KPIs por farmácia",
    description="Retorna métricas de desempenho por unidade de farmácia.",
)
async def kpis_por_farmacia(db: AsyncSession = Depends(get_db)):
    repo  = HistoricoRepository(db)
    dados = await repo.kpis_por_farmacia()
    return {"total": len(dados), "farmacias": dados}


@router.get(
    "/kpis/tempo-real",
    response_model=KpiTempoRealResponse,
    summary="KPIs operacionais em tempo real",
    description=(
        "Retorna métricas do estado atual da operação para dashboards em tempo real: "
        "pedidos ativos, em voo, concluídos, pontualidade histórica e ETA médio."
    ),
)
async def kpis_tempo_real(db: AsyncSession = Depends(get_db)):
    historico_repo = HistoricoRepository(db)
    kpis_historicos = await historico_repo.kpis_gerais()

    total_ativos = int(
        (
            await db.execute(
                select(func.count()).select_from(Pedido).where(Pedido.status.in_(STATUS_ATIVOS_MAPA))
            )
        ).scalar_one()
        or 0
    )
    pedidos_em_voo = int(
        (
            await db.execute(
                select(func.count()).select_from(Pedido).where(Pedido.status == StatusPedido.EM_VOO)
            )
        ).scalar_one()
        or 0
    )
    concluidos = int(
        (
            await db.execute(
                select(func.count()).select_from(Pedido).where(Pedido.status == StatusPedido.ENTREGUE)
            )
        ).scalar_one()
        or 0
    )
    pedidos_com_eta = list(
        (
            await db.execute(
                select(Pedido.estimativa_entrega_em).where(
                    Pedido.status.in_((StatusPedido.DESPACHADO, StatusPedido.EM_VOO)),
                    Pedido.estimativa_entrega_em.is_not(None),
                )
            )
        ).scalars().all()
    )
    agora = datetime.now()
    etas_restantes = [
        max(0.0, (estimativa - agora).total_seconds())
        for estimativa in pedidos_com_eta
        if estimativa is not None
    ]
    eta_medio_seg = (
        sum(etas_restantes) / len(etas_restantes)
        if etas_restantes else 0.0
    )

    return KpiTempoRealResponse(
        total_ativos=total_ativos,
        pedidos_em_voo=pedidos_em_voo,
        concluidos=concluidos,
        pontualidade_pct=float(kpis_historicos.get("taxa_pontualidade_pct") or 0.0),
        eta_medio_seg=float(eta_medio_seg),
    )

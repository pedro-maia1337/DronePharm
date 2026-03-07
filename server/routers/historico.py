# =============================================================================
# servidor/routers/historico.py
# Histórico de entregas e KPIs — /api/v1/historico
# =============================================================================

from typing import Optional
from fastapi import APIRouter, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.schemas.schemas import (
    HistoricoResponse, KpiGeralResponse, KpiFarmaciaResponse
)
from bd.database import get_db
from bd.repositories.historico_repo import HistoricoRepository

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

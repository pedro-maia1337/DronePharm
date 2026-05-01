from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from bd.database import get_db
from server.services.monitoramento import listar_snapshot_monitoramento

router = APIRouter()


@router.get(
    "/snapshot",
    summary="Snapshot consolidado do monitoramento",
    description=(
        "Retorna o estado unificado da frota em missão com drone, pedido ativo, "
        "posição atual, vetor e ETA. Ideal para sincronização inicial do mapa."
    ),
)
async def snapshot_monitoramento(db: AsyncSession = Depends(get_db)):
    return await listar_snapshot_monitoramento(db)

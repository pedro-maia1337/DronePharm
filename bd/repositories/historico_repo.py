# =============================================================================
# banco/repositories/historico_repo.py
# Operações de banco para historico_entregas e views de KPI
# =============================================================================

from typing import List, Optional
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from bd.models import HistoricoEntrega


class HistoricoRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def criar(
        self,
        pedido_id:         int,
        rota_id:           int,
        drone_id:          str,
        farmacia_id:       int,
        prioridade:        int,
        peso_kg:           float,
        distancia_km:      float,
        tempo_real_min:    Optional[float],
        entregue_no_prazo: bool,
    ) -> HistoricoEntrega:
        registro = HistoricoEntrega(
            pedido_id=pedido_id,
            rota_id=rota_id,
            drone_id=drone_id,
            farmacia_id=farmacia_id,
            prioridade=prioridade,
            peso_kg=peso_kg,
            distancia_km=distancia_km,
            tempo_real_min=tempo_real_min,
            entregue_no_prazo=entregue_no_prazo,
        )
        self.db.add(registro)
        await self.db.flush()
        await self.db.refresh(registro)
        return registro

    async def listar(
        self,
        drone_id:    Optional[str] = None,
        farmacia_id: Optional[int] = None,
        limite:      int           = 100,
    ) -> List[HistoricoEntrega]:
        query = select(HistoricoEntrega).order_by(HistoricoEntrega.criado_em.desc())
        if drone_id:
            query = query.where(HistoricoEntrega.drone_id == drone_id)
        if farmacia_id:
            query = query.where(HistoricoEntrega.farmacia_id == farmacia_id)
        query = query.limit(limite)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def kpis_gerais(self) -> dict:
        """Executa a view vw_kpis_gerais e retorna o resultado como dict."""
        result = await self.db.execute(text("SELECT * FROM vw_kpis_gerais"))
        row = result.mappings().fetchone()
        if not row:
            return {}
        return dict(row)

    async def kpis_por_farmacia(self) -> list:
        """Executa a view vw_entregas_por_farmacia."""
        result = await self.db.execute(
            text("SELECT * FROM vw_entregas_por_farmacia")
        )
        return [dict(r) for r in result.mappings().fetchall()]

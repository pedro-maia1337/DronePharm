# =============================================================================
# banco/repositories/historico_repo.py
# Operacoes de banco para historico_entregas e KPIs
# =============================================================================

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy import case, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from bd.models import Farmacia, HistoricoEntrega

log = logging.getLogger(__name__)


class HistoricoRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def criar(
        self,
        pedido_id: int,
        rota_id: int,
        drone_id: str,
        farmacia_id: int,
        prioridade: int,
        peso_kg: float,
        distancia_km: float,
        tempo_real_min: Optional[float],
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
        drone_id: Optional[str] = None,
        farmacia_id: Optional[int] = None,
        limite: int = 100,
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
        """
        Usa a view analitica quando disponivel. Em bancos sem a view ou com
        schema desatualizado, cai para agregacao direta na tabela.
        """
        try:
            result = await self.db.execute(text("SELECT * FROM vw_kpis_gerais"))
            row = result.mappings().fetchone()
            if row:
                return dict(row)
        except SQLAlchemyError as exc:
            await self.db.rollback()
            log.warning(
                "Falha ao consultar vw_kpis_gerais; usando fallback em tabela. erro=%s",
                exc,
            )

        return await self._kpis_gerais_fallback()

    async def kpis_por_farmacia(self) -> list:
        """
        Usa a view analitica por farmacia quando disponivel. Em bancos sem a
        view ou com schema divergente, recalcula via SQLAlchemy.
        """
        try:
            result = await self.db.execute(text("SELECT * FROM vw_entregas_por_farmacia"))
            return [dict(r) for r in result.mappings().fetchall()]
        except SQLAlchemyError as exc:
            await self.db.rollback()
            log.warning(
                "Falha ao consultar vw_entregas_por_farmacia; usando fallback em tabela. erro=%s",
                exc,
            )

        return await self._kpis_por_farmacia_fallback()

    async def _kpis_gerais_fallback(self) -> dict:
        query = select(
            func.count(HistoricoEntrega.id).label("total_entregas"),
            func.coalesce(
                func.sum(
                    case((HistoricoEntrega.entregue_no_prazo.is_(True), 1), else_=0)
                ),
                0,
            ).label("entregas_no_prazo"),
            func.coalesce(func.avg(HistoricoEntrega.tempo_real_min), 0.0).label("tempo_medio_min"),
            func.coalesce(func.avg(HistoricoEntrega.distancia_km), 0.0).label("distancia_media_km"),
            func.coalesce(func.sum(HistoricoEntrega.peso_kg), 0.0).label("peso_total_entregue_kg"),
        )
        result = await self.db.execute(query)
        row = result.mappings().fetchone()
        if not row:
            return {}

        dados = dict(row)
        total = int(dados.get("total_entregas") or 0)
        no_prazo = int(dados.get("entregas_no_prazo") or 0)
        dados["taxa_pontualidade_pct"] = (no_prazo * 100.0 / total) if total else 0.0
        return dados

    async def _kpis_por_farmacia_fallback(self) -> list:
        query = (
            select(
                HistoricoEntrega.farmacia_id.label("farmacia_id"),
                func.coalesce(Farmacia.nome, "Farmacia sem cadastro").label("farmacia"),
                func.coalesce(Farmacia.cidade, "").label("cidade"),
                func.coalesce(Farmacia.uf, "").label("uf"),
                func.count(HistoricoEntrega.id).label("total_entregas"),
                func.coalesce(
                    func.sum(
                        case((HistoricoEntrega.entregue_no_prazo.is_(True), 1), else_=0)
                    ),
                    0,
                ).label("entregas_no_prazo"),
                func.avg(HistoricoEntrega.tempo_real_min).label("tempo_medio_min"),
                func.avg(HistoricoEntrega.distancia_km).label("distancia_media_km"),
                func.sum(HistoricoEntrega.peso_kg).label("peso_total_kg"),
            )
            .select_from(HistoricoEntrega)
            .outerjoin(Farmacia, Farmacia.id == HistoricoEntrega.farmacia_id)
            .group_by(
                HistoricoEntrega.farmacia_id,
                Farmacia.nome,
                Farmacia.cidade,
                Farmacia.uf,
            )
            .order_by(
                func.count(HistoricoEntrega.id).desc(),
                HistoricoEntrega.farmacia_id.asc(),
            )
        )
        result = await self.db.execute(query)
        return [dict(r) for r in result.mappings().fetchall()]

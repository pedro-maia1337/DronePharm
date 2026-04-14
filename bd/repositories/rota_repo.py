# =============================================================================
# bd/repositories/rota_repo.py
# =============================================================================

from datetime import datetime
from typing import List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from bd.models import Rota


class RotaRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def criar(
        self,
        drone_id:    str,
        pedido_ids:  List[int],
        waypoints:   list,
        metricas:    dict,
        viavel:      bool,
        geracoes_ga: int = 0,
    ) -> int:
        """
        Persiste uma nova rota calculada.

        Parâmetros
        ----------
        geracoes_ga : número de gerações do GA utilizadas na otimização.
                      Exposto na resposta da API para fins de auditoria e
                      análise de desempenho do algoritmo.
        """
        rota = Rota(
            drone_id=drone_id,
            pedido_ids=pedido_ids,
            waypoints_json=waypoints,
            distancia_km=metricas.get("distancia_km", 0.0),
            tempo_min=metricas.get("tempo_min", 0.0),
            energia_wh=metricas.get("energia_wh", 0.0),
            carga_kg=metricas.get("carga_kg", 0.0),
            custo=metricas.get("custo_total", 0.0),
            viavel=viavel,
            geracoes_ga=geracoes_ga,
        )
        self.db.add(rota)
        await self.db.flush()
        await self.db.refresh(rota)
        return rota.id

    async def buscar_por_id(self, rota_id: int) -> Optional[Rota]:
        result = await self.db.execute(select(Rota).where(Rota.id == rota_id))
        return result.scalar_one_or_none()

    async def buscar_ativa_por_drone(self, drone_id: str) -> Optional[Rota]:
        """Rota em andamento (calculada ou em execução) mais recente do drone."""
        result = await self.db.execute(
            select(Rota)
            .where(
                Rota.drone_id == drone_id,
                Rota.status.in_(("calculada", "em_execucao")),
            )
            .order_by(Rota.criada_em.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def listar_recentes(
        self, limite: int = 50, drone_id: Optional[str] = None
    ) -> List[Rota]:
        query = select(Rota).order_by(Rota.criada_em.desc())
        if drone_id:
            query = query.where(Rota.drone_id == drone_id)
        result = await self.db.execute(query.limit(limite))
        return list(result.scalars().all())

    async def listar_por_status(self, status: str) -> List[Rota]:
        result = await self.db.execute(
            select(Rota).where(Rota.status == status).order_by(Rota.criada_em.desc())
        )
        return list(result.scalars().all())

    async def atualizar_status(self, rota_id: int, status: str):
        kwargs: dict = {"status": status}
        if status in ("concluida", "abortada"):
            kwargs["concluida_em"] = datetime.now()
        await self.db.execute(
            update(Rota).where(Rota.id == rota_id).values(**kwargs)
        )
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
        drone_id:   str,
        pedido_ids: List[int],
        waypoints:  list,
        metricas:   dict,
        viavel:     bool,
    ) -> int:
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
        )
        self.db.add(rota)
        await self.db.flush()
        await self.db.refresh(rota)
        return rota.id

    async def buscar_por_id(self, rota_id: int) -> Optional[Rota]:
        result = await self.db.execute(select(Rota).where(Rota.id == rota_id))
        return result.scalar_one_or_none()

    async def listar_recentes(self, limite: int = 50) -> List[Rota]:
        result = await self.db.execute(
            select(Rota).order_by(Rota.criada_em.desc()).limit(limite)
        )
        return list(result.scalars().all())

    async def atualizar_status(self, rota_id: int, status: str):
        kwargs = {"status": status}
        if status == "concluida":
            kwargs["concluida_em"] = datetime.now()
        await self.db.execute(
            update(Rota).where(Rota.id == rota_id).values(**kwargs)
        )

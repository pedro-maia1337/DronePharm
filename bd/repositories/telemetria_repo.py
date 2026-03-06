from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from bd.models import Telemetria


class TelemetriaRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def criar(self, **kwargs) -> Telemetria:
        registro = Telemetria(**kwargs)
        self.db.add(registro)
        await self.db.flush()
        await self.db.refresh(registro)
        return registro

    async def buscar_ultima(self, drone_id: str) -> Optional[Telemetria]:
        result = await self.db.execute(
            select(Telemetria)
            .where(Telemetria.drone_id == drone_id)
            .order_by(Telemetria.criado_em.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def historico(self, drone_id: str, limite: int = 100) -> List[Telemetria]:
        result = await self.db.execute(
            select(Telemetria)
            .where(Telemetria.drone_id == drone_id)
            .order_by(Telemetria.criado_em.desc())
            .limit(limite)
        )
        return list(result.scalars().all())

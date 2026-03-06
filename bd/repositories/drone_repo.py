from typing import List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from bd.models import Drone


class DroneRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def criar(self, **kwargs) -> Drone:
        drone = Drone(**kwargs)
        self.db.add(drone)
        await self.db.flush()
        await self.db.refresh(drone)
        return drone

    async def buscar_por_id(self, drone_id: str) -> Optional[Drone]:
        result = await self.db.execute(select(Drone).where(Drone.id == drone_id))
        return result.scalar_one_or_none()

    async def listar(self) -> List[Drone]:
        result = await self.db.execute(select(Drone).order_by(Drone.cadastrado_em))
        return list(result.scalars().all())

    async def atualizar_bateria(self, drone_id: str, bateria_pct: float):
        await self.db.execute(
            update(Drone).where(Drone.id == drone_id).values(bateria_pct=bateria_pct)
        )

    async def atualizar_posicao_e_bateria(
        self, drone_id: str,
        latitude: float, longitude: float,
        bateria_pct: float, status: str,
    ):
        await self.db.execute(
            update(Drone).where(Drone.id == drone_id).values(
                latitude_atual=latitude,
                longitude_atual=longitude,
                bateria_pct=bateria_pct,
                status=status,
            )
        )

# =============================================================================
# banco/repositories/drone_repo.py
# =============================================================================

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

    async def listar(self, status: Optional[str] = None) -> List[Drone]:
        query = select(Drone)
        if status:
            query = query.where(Drone.status == status)
        result = await self.db.execute(query.order_by(Drone.cadastrado_em))
        return list(result.scalars().all())

    async def buscar_disponiveis(self) -> List[Drone]:
        result = await self.db.execute(
            select(Drone).where(Drone.status == "aguardando").order_by(Drone.bateria_pct.desc())
        )
        return list(result.scalars().all())

    async def atualizar(self, drone_id: str, **campos) -> Optional[Drone]:
        campos_validos = {k: v for k, v in campos.items() if v is not None}
        if not campos_validos:
            return await self.buscar_por_id(drone_id)
        await self.db.execute(
            update(Drone).where(Drone.id == drone_id).values(**campos_validos)
        )
        return await self.buscar_por_id(drone_id)

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

    async def incrementar_missoes(self, drone_id: str):
        from sqlalchemy import func as sqlfunc
        drone = await self.buscar_por_id(drone_id)
        if drone:
            await self.db.execute(
                update(Drone).where(Drone.id == drone_id).values(
                    missoes_realizadas=drone.missoes_realizadas + 1,
                    status="aguardando",
                )
            )
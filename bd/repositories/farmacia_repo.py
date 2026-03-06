from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from bd.models import Farmacia


class FarmaciaRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def criar(self, **kwargs) -> Farmacia:
        farmacia = Farmacia(**kwargs)
        self.db.add(farmacia)
        await self.db.flush()
        await self.db.refresh(farmacia)
        return farmacia

    async def buscar_por_id(self, farmacia_id: int) -> Optional[Farmacia]:
        result = await self.db.execute(
            select(Farmacia).where(Farmacia.id == farmacia_id)
        )
        return result.scalar_one_or_none()

    async def listar(self, deposito: Optional[bool] = None) -> List[Farmacia]:
        query = select(Farmacia).where(Farmacia.ativa == True)
        if deposito is not None:
            query = query.where(Farmacia.deposito == deposito)
        result = await self.db.execute(query.order_by(Farmacia.nome))
        return list(result.scalars().all())

    async def buscar_deposito_principal(self) -> Optional[Farmacia]:
        result = await self.db.execute(
            select(Farmacia)
            .where(Farmacia.deposito == True, Farmacia.ativa == True)
            .order_by(Farmacia.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

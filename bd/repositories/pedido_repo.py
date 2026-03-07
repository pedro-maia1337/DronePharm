# =============================================================================
# banco/repositories/pedido_repo.py
# =============================================================================

from datetime import datetime
from typing import List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from bd.models import Pedido


class PedidoRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def criar(self, **kwargs) -> Pedido:
        pedido = Pedido(**kwargs)
        self.db.add(pedido)
        await self.db.flush()
        await self.db.refresh(pedido)
        return pedido

    async def buscar_por_id(self, pedido_id: int) -> Optional[Pedido]:
        result = await self.db.execute(select(Pedido).where(Pedido.id == pedido_id))
        return result.scalar_one_or_none()

    async def buscar_por_ids(self, ids: List[int]) -> List[Pedido]:
        result = await self.db.execute(select(Pedido).where(Pedido.id.in_(ids)))
        return list(result.scalars().all())

    async def listar_pendentes(self) -> List[Pedido]:
        result = await self.db.execute(
            select(Pedido)
            .where(Pedido.status == "pendente")
            .order_by(Pedido.prioridade.asc(), Pedido.criado_em.asc())
        )
        return list(result.scalars().all())

    async def listar(
        self,
        status:      Optional[str] = None,
        prioridade:  Optional[int] = None,
        farmacia_id: Optional[int] = None,
        limite:      int           = 100,
        offset:      int           = 0,
    ) -> List[Pedido]:
        query = select(Pedido)
        if status:
            query = query.where(Pedido.status == status)
        if prioridade:
            query = query.where(Pedido.prioridade == prioridade)
        if farmacia_id:
            query = query.where(Pedido.farmacia_id == farmacia_id)
        query = query.order_by(Pedido.criado_em.desc()).offset(offset).limit(limite)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def atualizar_status(self, pedido_id: int, status: str):
        kwargs: dict = {"status": status}
        if status == "entregue":
            kwargs["entregue_em"] = datetime.now()
        await self.db.execute(
            update(Pedido).where(Pedido.id == pedido_id).values(**kwargs)
        )

    async def atualizar_status_lote(
        self,
        ids:     List[int],
        status:  str,
        rota_id: Optional[int] = None,
    ):
        kwargs: dict = {"status": status}
        if rota_id is not None:
            kwargs["rota_id"] = rota_id
        if status == "entregue":
            kwargs["entregue_em"] = datetime.now()
        await self.db.execute(
            update(Pedido).where(Pedido.id.in_(ids)).values(**kwargs)
        )
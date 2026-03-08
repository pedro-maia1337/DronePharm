# =============================================================================
# banco/repositories/pedido_repo.py
# Inclui gravação automática de rastreabilidade a cada mudança de status
# =============================================================================

import logging
from datetime import datetime
from typing import List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from bd.models import Pedido, RastreabilidadePedido

log = logging.getLogger(__name__)


class PedidoRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def criar(self, **kwargs) -> Pedido:
        pedido = Pedido(**kwargs)
        self.db.add(pedido)
        await self.db.flush()
        await self.db.refresh(pedido)
        # Rastreabilidade: criação
        await self._rastrear(pedido.id, "—", "pendente", observacao="Pedido criado")
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

    async def atualizar_status(self, pedido_id: int, status: str,
                                drone_id: Optional[str] = None,
                                rota_id: Optional[int] = None):
        pedido = await self.buscar_por_id(pedido_id)
        status_anterior = pedido.status if pedido else "desconhecido"

        kwargs: dict = {"status": status}
        if status == "entregue":
            kwargs["entregue_em"] = datetime.now()
        await self.db.execute(
            update(Pedido).where(Pedido.id == pedido_id).values(**kwargs)
        )
        await self._rastrear(pedido_id, status_anterior, status,
                             drone_id=drone_id, rota_id=rota_id)

    async def atualizar_status_lote(
        self,
        ids:      List[int],
        status:   str,
        rota_id:  Optional[int] = None,
        drone_id: Optional[str] = None,
    ):
        pedidos_antes = await self.buscar_por_ids(ids)
        status_map    = {p.id: p.status for p in pedidos_antes}

        kwargs: dict = {"status": status}
        if rota_id is not None:
            kwargs["rota_id"] = rota_id
        if status == "entregue":
            kwargs["entregue_em"] = datetime.now()

        await self.db.execute(
            update(Pedido).where(Pedido.id.in_(ids)).values(**kwargs)
        )
        for pid in ids:
            await self._rastrear(
                pid,
                status_map.get(pid, "desconhecido"),
                status,
                drone_id=drone_id,
                rota_id=rota_id,
            )

    # ── Rastreabilidade interna ───────────────────────────────────────────────

    async def _rastrear(
        self,
        pedido_id:   int,
        status_de:   str,
        status_para: str,
        drone_id:    Optional[str]   = None,
        rota_id:     Optional[int]   = None,
        latitude:    Optional[float] = None,
        longitude:   Optional[float] = None,
        observacao:  Optional[str]   = None,
    ):
        """Grava silenciosamente uma linha na tabela rastreabilidade_pedidos."""
        try:
            entry = RastreabilidadePedido(
                pedido_id=pedido_id,
                status_de=status_de,
                status_para=status_para,
                drone_id=drone_id,
                rota_id=rota_id,
                latitude=latitude,
                longitude=longitude,
                observacao=observacao,
            )
            self.db.add(entry)
            await self.db.flush()
        except Exception as exc:
            # Rastreabilidade nunca deve bloquear a operação principal
            log.warning(f"Falha ao registrar rastreabilidade pedido={pedido_id}: {exc}")
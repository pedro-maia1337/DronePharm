# =============================================================================
# banco/repositories/pedido_repo.py
# Inclui gravação automática de rastreabilidade a cada mudança de status
# =============================================================================

import logging
from datetime import datetime, timezone
from typing import List, Optional, Sequence
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from bd.models import Pedido, RastreabilidadePedido
from domain.pedido_estado import (
    OperacaoTransicaoPedido,
    TransicaoPedidoInvalidaError,
    validar_transicao_pedido,
)
from server.websocket.connection_manager import manager

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
        await self._emitir_evento_status(
            pedido.id,
            "pedido_criado",
            status_de=None,
            status_para="pendente",
            rota_id=pedido.rota_id,
        )
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
        statuses:    Optional[Sequence[str]] = None,
        prioridade:  Optional[int] = None,
        farmacia_id: Optional[int] = None,
        limite:      int           = 100,
        offset:      int           = 0,
    ) -> List[Pedido]:
        query = select(Pedido)
        if statuses:
            query = query.where(Pedido.status.in_(tuple(statuses)))
        elif status:
            query = query.where(Pedido.status == status)
        if prioridade:
            query = query.where(Pedido.prioridade == prioridade)
        if farmacia_id:
            query = query.where(Pedido.farmacia_id == farmacia_id)
        query = query.order_by(Pedido.criado_em.desc()).offset(offset).limit(limite)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def contar(
        self,
        status:      Optional[str] = None,
        statuses:    Optional[Sequence[str]] = None,
        prioridade:  Optional[int] = None,
        farmacia_id: Optional[int] = None,
    ) -> int:
        query = select(func.count()).select_from(Pedido)
        if statuses:
            query = query.where(Pedido.status.in_(tuple(statuses)))
        elif status:
            query = query.where(Pedido.status == status)
        if prioridade:
            query = query.where(Pedido.prioridade == prioridade)
        if farmacia_id:
            query = query.where(Pedido.farmacia_id == farmacia_id)
        result = await self.db.execute(query)
        return int(result.scalar_one() or 0)

    async def atualizar(self, pedido_id: int, **campos) -> Optional[Pedido]:
        campos_validos = {k: v for k, v in campos.items() if v is not None}
        if "status" in campos_validos:
            raise ValueError(
                "O status do pedido não pode ser alterado via atualização genérica; "
                "use os endpoints dedicados ou operações de rota."
            )
        pedido = await self.buscar_por_id(pedido_id)
        if not pedido:
            return None
        if not campos_validos:
            return pedido

        await self.db.execute(
            update(Pedido).where(Pedido.id == pedido_id).values(**campos_validos)
        )

        return await self.buscar_por_id(pedido_id)

    async def atualizar_status(
        self,
        pedido_id: int,
        status: str,
        operacao: OperacaoTransicaoPedido,
        drone_id: Optional[str] = None,
        rota_id: Optional[int] = None,
        despachado_em: Optional[datetime] = None,
        estimativa_entrega_em: Optional[datetime] = None,
    ):
        pedido = await self.buscar_por_id(pedido_id)
        if not pedido:
            return
        status_anterior = pedido.status
        validar_transicao_pedido(status_anterior, status, operacao)

        kwargs: dict = {"status": status}
        if rota_id is not None:
            kwargs["rota_id"] = rota_id
        if status == "entregue":
            kwargs["entregue_em"] = datetime.now()
        if status == "pendente":
            kwargs["rota_id"] = None
            kwargs["despachado_em"] = None
            kwargs["estimativa_entrega_em"] = None
        if status == "despachado":
            kwargs["despachado_em"] = despachado_em or datetime.now()
        if estimativa_entrega_em is not None:
            kwargs["estimativa_entrega_em"] = estimativa_entrega_em
        await self.db.execute(
            update(Pedido).where(Pedido.id == pedido_id).values(**kwargs)
        )
        await self._rastrear(pedido_id, status_anterior, status,
                             drone_id=drone_id, rota_id=rota_id)
        if operacao not in (
            OperacaoTransicaoPedido.TELEM_DESPACHO,
            OperacaoTransicaoPedido.TELEM_EM_VOO,
        ):
            await self._emitir_evento_status(
                pedido_id,
                self._nome_evento_status(status),
                status_de=status_anterior,
                status_para=status,
                drone_id=drone_id,
                rota_id=rota_id,
            )

    async def atualizar_status_lote(
        self,
        ids:      List[int],
        status:   str,
        operacao: OperacaoTransicaoPedido,
        rota_id:  Optional[int] = None,
        drone_id: Optional[str] = None,
        despachado_em: Optional[datetime] = None,
        estimativa_entrega_em: Optional[datetime] = None,
    ):
        pedidos_antes = await self.buscar_por_ids(ids)
        status_map    = {p.id: p.status for p in pedidos_antes}

        for p in pedidos_antes:
            validar_transicao_pedido(p.status, status, operacao)

        kwargs: dict = {"status": status}
        if rota_id is not None:
            kwargs["rota_id"] = rota_id
        if status == "entregue":
            kwargs["entregue_em"] = datetime.now()
        if status == "pendente":
            kwargs["rota_id"] = None
            kwargs["despachado_em"] = None
            kwargs["estimativa_entrega_em"] = None
        if status == "despachado":
            kwargs["despachado_em"] = despachado_em or datetime.now()
        if estimativa_entrega_em is not None:
            kwargs["estimativa_entrega_em"] = estimativa_entrega_em

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
            if operacao not in (
                OperacaoTransicaoPedido.TELEM_DESPACHO,
                OperacaoTransicaoPedido.TELEM_EM_VOO,
            ):
                await self._emitir_evento_status(
                    pid,
                    self._nome_evento_status(status),
                    status_de=status_map.get(pid),
                    status_para=status,
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

    @staticmethod
    def _nome_evento_status(status: str) -> str:
        return f"pedido_{status}"

    async def _emitir_evento_status(
        self,
        pedido_id: int,
        evento: str,
        *,
        status_de: Optional[str],
        status_para: Optional[str],
        drone_id: Optional[str] = None,
        rota_id: Optional[int] = None,
    ) -> None:
        await manager.broadcast_evento_pedido(
            evento,
            {
                "pedido_id": pedido_id,
                "status_de": status_de,
                "status_para": status_para,
                "drone_id": drone_id,
                "rota_id": rota_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

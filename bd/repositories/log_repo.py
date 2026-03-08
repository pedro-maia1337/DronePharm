# =============================================================================
# banco/repositories/log_repo.py
# Repositório para LogSistema e RastreabilidadePedido
# =============================================================================

import logging
from typing import List, Optional
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from bd.models import LogSistema, RastreabilidadePedido

log = logging.getLogger(__name__)


class LogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def registrar(
        self,
        nivel:      str,
        categoria:  str,
        mensagem:   str,
        drone_id:   Optional[str] = None,
        pedido_id:  Optional[int] = None,
        rota_id:    Optional[int] = None,
        dados_json: dict          = None,
    ) -> LogSistema:
        entry = LogSistema(
            nivel=nivel,
            categoria=categoria,
            mensagem=mensagem,
            drone_id=drone_id,
            pedido_id=pedido_id,
            rota_id=rota_id,
            dados_json=dados_json or {},
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def listar(
        self,
        nivel:      Optional[str] = None,
        categoria:  Optional[str] = None,
        drone_id:   Optional[str] = None,
        rota_id:    Optional[int] = None,
        limite:     int           = 200,
    ) -> List[LogSistema]:
        query = select(LogSistema)
        if nivel:
            query = query.where(LogSistema.nivel == nivel.upper())
        if categoria:
            query = query.where(LogSistema.categoria == categoria.upper())
        if drone_id:
            query = query.where(LogSistema.drone_id == drone_id)
        if rota_id:
            query = query.where(LogSistema.rota_id == rota_id)
        query = query.order_by(desc(LogSistema.criado_em)).limit(limite)
        result = await self.db.execute(query)
        return list(result.scalars().all())


class RastreabilidadeRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def registrar_transicao(
        self,
        pedido_id:   int,
        status_de:   str,
        status_para: str,
        drone_id:    Optional[str]   = None,
        rota_id:     Optional[int]   = None,
        latitude:    Optional[float] = None,
        longitude:   Optional[float] = None,
        observacao:  Optional[str]   = None,
    ) -> RastreabilidadePedido:
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
        return entry

    async def trilha_pedido(self, pedido_id: int) -> List[RastreabilidadePedido]:
        result = await self.db.execute(
            select(RastreabilidadePedido)
            .where(RastreabilidadePedido.pedido_id == pedido_id)
            .order_by(RastreabilidadePedido.criado_em)
        )
        return list(result.scalars().all())

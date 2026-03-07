# =============================================================================
# banco/repositories/farmacia_repo.py
# =============================================================================

import logging
from typing import List, Optional
from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession
from bd.models import Farmacia

log = logging.getLogger(__name__)

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

    async def listar(self, deposito: Optional[bool] = None, so_ativas: bool = True) -> List[Farmacia]:
        query = select(Farmacia)
        if so_ativas:
            query = query.where(Farmacia.ativa == True)
        if deposito is not None:
            query = query.where(Farmacia.deposito == deposito)
        result = await self.db.execute(query.order_by(Farmacia.nome))
        return list(result.scalars().all())

    async def buscar_deposito_principal(self) -> Optional[Farmacia]:
        """
        Busca a farmácia-polo principal (depósito).
        Usa raw SQL para evitar erro caso a coluna criada_em ainda não exista
        no banco (antes de executar 003_add_farmacias_criada_em.sql).
        """
        try:
            # Tenta via ORM (funciona após a migração 003)
            result = await self.db.execute(
                select(Farmacia)
                .where(Farmacia.deposito == True, Farmacia.ativa == True)
                .order_by(Farmacia.id)
                .limit(1)
            )
            return result.scalar_one_or_none()

        except Exception as orm_exc:
            # Fallback: raw SQL sem colunas que podem estar faltando
            log.warning(
                f"ORM falhou ao buscar depósito ({orm_exc}). "
                "Usando raw SQL — execute banco/migrations/003_add_farmacias_criada_em.sql "
                "para corrigir a estrutura do banco."
            )
            try:
                result = await self.db.execute(
                    text(
                        "SELECT id, nome, latitude, longitude, "
                        "       endereco, cidade, uf, deposito, ativa "
                        "FROM farmacias "
                        "WHERE deposito = TRUE AND ativa = TRUE "
                        "ORDER BY id LIMIT 1"
                    )
                )
                row = result.mappings().fetchone()
                if not row:
                    return None

                # Monta objeto Farmacia sem criada_em
                f = Farmacia()
                f.id        = row["id"]
                f.nome      = row["nome"]
                f.latitude  = row["latitude"]
                f.longitude = row["longitude"]
                f.endereco  = row["endereco"] or ""
                f.cidade    = row["cidade"] or ""
                f.uf        = row["uf"] or ""
                f.deposito  = row["deposito"]
                f.ativa     = row["ativa"]
                # criada_em fica None — não causa problemas no código
                f.criada_em = None
                return f

            except Exception as raw_exc:
                log.error(f"Fallback raw SQL também falhou: {raw_exc}")
                return None

    async def atualizar(self, farmacia_id: int, **campos) -> Optional[Farmacia]:
        campos_validos = {k: v for k, v in campos.items() if v is not None}
        if not campos_validos:
            return await self.buscar_por_id(farmacia_id)
        await self.db.execute(
            update(Farmacia).where(Farmacia.id == farmacia_id).values(**campos_validos)
        )
        return await self.buscar_por_id(farmacia_id)

    async def desativar(self, farmacia_id: int):
        await self.db.execute(
            update(Farmacia).where(Farmacia.id == farmacia_id).values(ativa=False)
        )
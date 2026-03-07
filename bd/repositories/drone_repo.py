# =============================================================================
# banco/repositories/drone_repo.py
# =============================================================================

import logging
from typing import List, Optional
from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession
from bd.models import Drone

log = logging.getLogger(__name__)

# Colunas seguras — presentes no banco desde o início (sem timestamps opcionais)
_COLS_SEGURAS = (
    "id, nome, capacidade_max_kg, autonomia_max_km, velocidade_ms, "
    "bateria_pct, status, latitude_atual, longitude_atual, missoes_realizadas"
)


def _row_para_drone(row: dict) -> Drone:
    """Converte um mapeamento raw SQL em objeto Drone sem usar o ORM completo."""
    d = Drone()
    d.id                 = row["id"]
    d.nome               = row["nome"]
    d.capacidade_max_kg  = row["capacidade_max_kg"]
    d.autonomia_max_km   = row["autonomia_max_km"]
    d.velocidade_ms      = row["velocidade_ms"]
    d.bateria_pct        = row["bateria_pct"]
    d.status             = row["status"]
    d.latitude_atual     = row.get("latitude_atual")
    d.longitude_atual    = row.get("longitude_atual")
    d.missoes_realizadas = row["missoes_realizadas"]
    d.cadastrado_em      = row.get("cadastrado_em")   # None se coluna ainda ausente
    d.atualizado_em      = row.get("atualizado_em")
    return d


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
        """Busca drone por ID com fallback seguro se timestamps ausentes no banco."""
        try:
            result = await self.db.execute(
                select(Drone).where(Drone.id == drone_id)
            )
            return result.scalar_one_or_none()
        except Exception as exc:
            log.warning(
                f"ORM falhou ao buscar drone '{drone_id}' ({exc}). "
                "Usando raw SQL — execute banco/migrations/004_add_drones_timestamps.sql"
            )
            result = await self.db.execute(
                text(f"SELECT {_COLS_SEGURAS} FROM drones WHERE id = :id"),
                {"id": drone_id},
            )
            row = result.mappings().fetchone()
            return _row_para_drone(row) if row else None

    async def listar(self, status: Optional[str] = None) -> List[Drone]:
        try:
            query = select(Drone)
            if status:
                query = query.where(Drone.status == status)
            result = await self.db.execute(query.order_by(Drone.id))
            return list(result.scalars().all())
        except Exception as exc:
            log.warning(f"ORM falhou ao listar drones ({exc}). Usando raw SQL.")
            sql = f"SELECT {_COLS_SEGURAS} FROM drones"
            params: dict = {}
            if status:
                sql += " WHERE status = :status"
                params["status"] = status
            sql += " ORDER BY id"
            result = await self.db.execute(text(sql), params)
            return [_row_para_drone(r) for r in result.mappings().all()]

    async def buscar_disponiveis(self) -> List[Drone]:
        """Retorna drones com status='aguardando' ordenados por bateria decrescente."""
        try:
            result = await self.db.execute(
                select(Drone)
                .where(Drone.status == "aguardando")
                .order_by(Drone.bateria_pct.desc())
            )
            return list(result.scalars().all())
        except Exception as exc:
            log.warning(f"ORM falhou em buscar_disponiveis ({exc}). Usando raw SQL.")
            result = await self.db.execute(
                text(
                    f"SELECT {_COLS_SEGURAS} FROM drones "
                    "WHERE status = 'aguardando' ORDER BY bateria_pct DESC"
                )
            )
            return [_row_para_drone(r) for r in result.mappings().all()]

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
        drone = await self.buscar_por_id(drone_id)
        if drone:
            await self.db.execute(
                update(Drone).where(Drone.id == drone_id).values(
                    missoes_realizadas=drone.missoes_realizadas + 1,
                    status="aguardando",
                )
            )
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bd.repositories.historico_repo import HistoricoRepository


def _result_one(row):
    result = MagicMock()
    result.mappings.return_value.fetchone.return_value = row
    return result


def _result_many(rows):
    result = MagicMock()
    result.mappings.return_value.fetchall.return_value = rows
    return result


@pytest.mark.asyncio
async def test_kpis_gerais_faz_fallback_quando_view_falha():
    db = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            SQLAlchemyError("view ausente"),
            _result_one(
                {
                    "total_entregas": 4,
                    "entregas_no_prazo": 3,
                    "tempo_medio_min": 12.5,
                    "distancia_media_km": 4.2,
                    "peso_total_entregue_kg": 7.0,
                }
            ),
        ]
    )

    repo = HistoricoRepository(db)
    dados = await repo.kpis_gerais()

    assert dados["total_entregas"] == 4
    assert dados["entregas_no_prazo"] == 3
    assert dados["taxa_pontualidade_pct"] == 75.0
    assert dados["tempo_medio_min"] == 12.5
    assert db.execute.await_count == 2
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_kpis_gerais_fallback_retorna_zeros_quando_sem_historico():
    db = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            SQLAlchemyError("view ausente"),
            _result_one(
                {
                    "total_entregas": 0,
                    "entregas_no_prazo": 0,
                    "tempo_medio_min": 0.0,
                    "distancia_media_km": 0.0,
                    "peso_total_entregue_kg": 0.0,
                }
            ),
        ]
    )

    repo = HistoricoRepository(db)
    dados = await repo.kpis_gerais()

    assert dados["total_entregas"] == 0
    assert dados["taxa_pontualidade_pct"] == 0.0
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_kpis_por_farmacia_faz_fallback_quando_view_falha():
    db = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            SQLAlchemyError("view ausente"),
            _result_many(
                [
                    {
                        "farmacia_id": 1,
                        "farmacia": "Farmacia Centro",
                        "cidade": "Belo Horizonte",
                        "uf": "MG",
                        "total_entregas": 8,
                        "entregas_no_prazo": 7,
                        "tempo_medio_min": 11.2,
                        "distancia_media_km": 3.8,
                        "peso_total_kg": 6.4,
                    }
                ]
            ),
        ]
    )

    repo = HistoricoRepository(db)
    dados = await repo.kpis_por_farmacia()

    assert len(dados) == 1
    assert dados[0]["farmacia_id"] == 1
    assert dados[0]["total_entregas"] == 8
    assert db.execute.await_count == 2
    db.rollback.assert_awaited_once()

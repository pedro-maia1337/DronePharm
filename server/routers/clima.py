# =============================================================================
# servidor/routers/clima.py
# Dados climaticos via OpenWeatherMap - /api/v1/clima
# =============================================================================

import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.schemas.schemas import ClimaResponse
from bd.database import get_db
from bd.repositories.farmacia_repo import FarmaciaRepository
from apis.clima import cliente_clima

router = APIRouter()


async def _consultar_clima_async(lat: float, lon: float, forcar: bool = False):
    """
    Executa o cliente sincrono de clima em uma thread separada.

    O cliente atual usa requests.get(). Se ele rodar direto dentro do endpoint
    async, uma consulta lenta pode bloquear o event loop do worker inteiro.
    """
    return await asyncio.to_thread(
        cliente_clima.consultar,
        lat,
        lon,
        forcar_atualizacao=forcar,
    )


@router.get(
    "/",
    response_model=ClimaResponse,
    summary="Consultar clima por coordenada",
    description=(
        "Retorna condicoes climaticas reais via OpenWeatherMap. "
        "Inclui `operacional` indicando se as condicoes permitem voo seguro."
    ),
)
async def consultar_clima(
    lat: float = Query(..., ge=-90, le=90, description="Latitude"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude"),
    forcar: bool = Query(False, description="Ignorar cache e forcar nova consulta"),
):
    if not cliente_clima:
        raise HTTPException(
            status_code=503,
            detail="API de clima nao configurada. Defina OPENWEATHER_API_KEY no .env.",
        )

    dados = await _consultar_clima_async(lat, lon, forcar=forcar)
    if not dados:
        raise HTTPException(status_code=503, detail="Falha ao consultar OpenWeatherMap.")

    return ClimaResponse(
        latitude=dados.latitude,
        longitude=dados.longitude,
        temperatura_c=dados.temperatura_c,
        vento_ms=dados.vento_ms,
        direcao_vento_grau=dados.direcao_vento_grau,
        rajada_ms=dados.rajada_ms,
        umidade_pct=dados.umidade_pct,
        descricao=dados.descricao,
        visibilidade_m=dados.visibilidade_m,
        operacional=dados.operacional,
        consultado_em=datetime.now(),
    )


@router.get(
    "/deposito",
    response_model=ClimaResponse,
    summary="Clima no deposito principal",
    description="Consulta o clima diretamente na coordenada do deposito cadastrado no banco.",
)
async def clima_deposito(db: AsyncSession = Depends(get_db)):
    if not cliente_clima:
        raise HTTPException(status_code=503, detail="API de clima nao configurada.")

    farmacia_repo = FarmaciaRepository(db)
    deposito = await farmacia_repo.buscar_deposito_principal()
    if not deposito:
        raise HTTPException(status_code=404, detail="Nenhum deposito cadastrado.")

    dados = await _consultar_clima_async(deposito.latitude, deposito.longitude)
    if not dados:
        raise HTTPException(status_code=503, detail="Falha ao consultar OpenWeatherMap.")

    return ClimaResponse(
        latitude=dados.latitude,
        longitude=dados.longitude,
        temperatura_c=dados.temperatura_c,
        vento_ms=dados.vento_ms,
        direcao_vento_grau=dados.direcao_vento_grau,
        rajada_ms=dados.rajada_ms,
        umidade_pct=dados.umidade_pct,
        descricao=dados.descricao,
        visibilidade_m=dados.visibilidade_m,
        operacional=dados.operacional,
        consultado_em=datetime.now(),
    )

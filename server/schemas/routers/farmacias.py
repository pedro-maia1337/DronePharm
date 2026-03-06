# =============================================================================
# servidor/routers/farmacias.py
# =============================================================================

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from server.schemas.schemas import FarmaciaCreate, FarmaciaResponse
from bd.database import get_db
from bd.repositories.farmacia_repo import FarmaciaRepository

router = APIRouter()


@router.post("/", response_model=FarmaciaResponse, status_code=201, summary="Cadastrar farmácia")
async def cadastrar_farmacia(body: FarmaciaCreate, db: AsyncSession = Depends(get_db)):
    repo = FarmaciaRepository(db)
    return await repo.criar(**body.model_dump())


@router.get("/", summary="Listar farmácias")
async def listar_farmacias(
    deposito: Optional[bool] = Query(None, description="Filtrar só farmácias-polo"),
    db: AsyncSession = Depends(get_db),
):
    repo      = FarmaciaRepository(db)
    farmacias = await repo.listar(deposito=deposito)
    return {"total": len(farmacias), "farmacias": farmacias}


@router.get("/deposito", response_model=FarmaciaResponse, summary="Farmácia-polo principal (depósito)")
async def deposito_principal(db: AsyncSession = Depends(get_db)):
    repo     = FarmaciaRepository(db)
    farmacia = await repo.buscar_deposito_principal()
    if not farmacia:
        raise HTTPException(status_code=404, detail="Nenhum depósito cadastrado.")
    return farmacia


@router.get("/{farmacia_id}", response_model=FarmaciaResponse, summary="Buscar farmácia por ID")
async def buscar_farmacia(farmacia_id: int, db: AsyncSession = Depends(get_db)):
    repo     = FarmaciaRepository(db)
    farmacia = await repo.buscar_por_id(farmacia_id)
    if not farmacia:
        raise HTTPException(status_code=404, detail=f"Farmácia {farmacia_id} não encontrada.")
    return farmacia

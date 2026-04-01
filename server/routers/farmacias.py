# =============================================================================
# servidor/routers/farmacias.py
# CRUD completo de farmácias — /api/v1/farmacias
# =============================================================================

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.schemas.schemas import FarmaciaCreate, FarmaciaUpdate, FarmaciaResponse
from bd.database import get_db
from bd.repositories.farmacia_repo import FarmaciaRepository
from server.security.rest_auth import require_rest_admin

router = APIRouter()


@router.post(
    "/",
    response_model=FarmaciaResponse,
    status_code=201,
    summary="Cadastrar farmácia",
    description="Registra uma nova unidade. Use `deposito=true` para definir a farmácia-polo.",
)
async def cadastrar_farmacia(
    body: FarmaciaCreate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_rest_admin),
):
    repo = FarmaciaRepository(db)
    return await repo.criar(**body.model_dump())


@router.get(
    "/",
    summary="Listar farmácias",
    description="Retorna todas as farmácias ativas. Filtre por `deposito=true` para ver só polos.",
)
async def listar_farmacias(
    deposito: Optional[bool] = Query(None, description="true = só polos | false = só filiais"),
    db: AsyncSession = Depends(get_db),
):
    repo      = FarmaciaRepository(db)
    farmacias = await repo.listar(deposito=deposito)
    return {"total": len(farmacias), "farmacias": farmacias}


@router.get(
    "/deposito",
    response_model=FarmaciaResponse,
    summary="Farmácia-polo principal (depósito)",
    description="Retorna o depósito principal — base de decolagem e pouso dos drones.",
)
async def deposito_principal(db: AsyncSession = Depends(get_db)):
    repo     = FarmaciaRepository(db)
    farmacia = await repo.buscar_deposito_principal()
    if not farmacia:
        raise HTTPException(status_code=404, detail="Nenhum depósito cadastrado.")
    return farmacia


@router.get(
    "/{farmacia_id}",
    response_model=FarmaciaResponse,
    summary="Buscar farmácia por ID",
)
async def buscar_farmacia(farmacia_id: int, db: AsyncSession = Depends(get_db)):
    repo     = FarmaciaRepository(db)
    farmacia = await repo.buscar_por_id(farmacia_id)
    if not farmacia:
        raise HTTPException(status_code=404, detail=f"Farmácia {farmacia_id} não encontrada.")
    return farmacia


@router.patch(
    "/{farmacia_id}",
    response_model=FarmaciaResponse,
    summary="Atualizar farmácia",
    description="Atualiza campos da farmácia. Apenas os campos enviados são modificados.",
)
async def atualizar_farmacia(
    farmacia_id: int,
    body: FarmaciaUpdate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_rest_admin),
):
    repo     = FarmaciaRepository(db)
    farmacia = await repo.buscar_por_id(farmacia_id)
    if not farmacia:
        raise HTTPException(status_code=404, detail=f"Farmácia {farmacia_id} não encontrada.")
    atualizada = await repo.atualizar(farmacia_id, **body.model_dump(exclude_none=True))
    return atualizada


@router.delete(
    "/{farmacia_id}",
    status_code=204,
    summary="Desativar farmácia",
    description="Marca a farmácia como inativa (soft delete). Não remove do banco.",
)
async def desativar_farmacia(
    farmacia_id: int,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_rest_admin),
):
    repo     = FarmaciaRepository(db)
    farmacia = await repo.buscar_por_id(farmacia_id)
    if not farmacia:
        raise HTTPException(status_code=404, detail=f"Farmácia {farmacia_id} não encontrada.")
    if farmacia.deposito:
        raise HTTPException(
            status_code=409,
            detail="Não é possível desativar a farmácia-polo (depósito).",
        )
    await repo.desativar(farmacia_id)

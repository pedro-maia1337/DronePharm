# =============================================================================
# servidor/routers/drones.py
# CRUD completo de drones — /api/v1/drones
# =============================================================================

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.schemas.schemas import DroneCreate, DroneUpdate, DroneResponse
from bd.database import get_db
from bd.repositories.drone_repo import DroneRepository

router = APIRouter()


@router.post(
    "/",
    response_model=DroneResponse,
    status_code=201,
    summary="Cadastrar drone",
    description="Registra um novo VANT na frota.",
)
async def cadastrar_drone(body: DroneCreate, db: AsyncSession = Depends(get_db)):
    repo = DroneRepository(db)
    if await repo.buscar_por_id(body.id):
        raise HTTPException(status_code=409, detail=f"Drone '{body.id}' já cadastrado.")
    return await repo.criar(**body.model_dump())


@router.get(
    "/",
    summary="Listar drones",
    description="Retorna todos os drones. Filtre por `status` para ver só os disponíveis.",
)
async def listar_drones(
    status: Optional[str] = Query(
        None,
        description="aguardando | em_voo | retornando | carregando | manutencao | emergencia"
    ),
    db: AsyncSession = Depends(get_db),
):
    repo   = DroneRepository(db)
    drones = await repo.listar(status=status)
    return {"total": len(drones), "drones": drones}


@router.get(
    "/disponiveis",
    summary="Listar drones disponíveis",
    description="Retorna drones com status 'aguardando', ordenados por maior bateria.",
)
async def listar_disponiveis(db: AsyncSession = Depends(get_db)):
    repo   = DroneRepository(db)
    drones = await repo.buscar_disponiveis()
    return {"total": len(drones), "drones": drones}


@router.get(
    "/{drone_id}",
    response_model=DroneResponse,
    summary="Buscar drone por ID",
)
async def buscar_drone(drone_id: str, db: AsyncSession = Depends(get_db)):
    repo  = DroneRepository(db)
    drone = await repo.buscar_por_id(drone_id)
    if not drone:
        raise HTTPException(status_code=404, detail=f"Drone '{drone_id}' não encontrado.")
    return drone


@router.patch(
    "/{drone_id}",
    response_model=DroneResponse,
    summary="Atualizar drone",
    description="Atualiza status, bateria ou posição. Campos omitidos não são alterados.",
)
async def atualizar_drone(
    drone_id: str,
    body: DroneUpdate,
    db: AsyncSession = Depends(get_db),
):
    repo  = DroneRepository(db)
    drone = await repo.buscar_por_id(drone_id)
    if not drone:
        raise HTTPException(status_code=404, detail=f"Drone '{drone_id}' não encontrado.")
    atualizado = await repo.atualizar(drone_id, **body.model_dump(exclude_none=True))
    return atualizado


@router.patch(
    "/{drone_id}/bateria",
    summary="Atualizar nível de bateria",
)
async def atualizar_bateria(
    drone_id:    str,
    bateria_pct: float = Query(..., ge=0.0, le=1.0, description="Nível de bateria (0.0 a 1.0)"),
    db: AsyncSession = Depends(get_db),
):
    repo  = DroneRepository(db)
    drone = await repo.buscar_por_id(drone_id)
    if not drone:
        raise HTTPException(status_code=404, detail=f"Drone '{drone_id}' não encontrado.")
    await repo.atualizar_bateria(drone_id, bateria_pct)
    return {"drone_id": drone_id, "bateria_pct": bateria_pct, "mensagem": "Bateria atualizada."}


@router.patch(
    "/{drone_id}/status",
    summary="Atualizar status do drone",
    description="Atualiza manualmente o status operacional do drone.",
)
async def atualizar_status(
    drone_id: str,
    status: str = Query(
        ...,
        description="aguardando | em_voo | retornando | carregando | manutencao | emergencia"
    ),
    db: AsyncSession = Depends(get_db),
):
    STATUS_VALIDOS = {"aguardando", "em_voo", "retornando", "carregando", "manutencao", "emergencia"}
    if status not in STATUS_VALIDOS:
        raise HTTPException(status_code=422, detail=f"Status inválido. Use: {', '.join(STATUS_VALIDOS)}")
    repo  = DroneRepository(db)
    drone = await repo.buscar_por_id(drone_id)
    if not drone:
        raise HTTPException(status_code=404, detail=f"Drone '{drone_id}' não encontrado.")
    await repo.atualizar(drone_id, status=status)
    return {"drone_id": drone_id, "status": status, "mensagem": "Status atualizado."}
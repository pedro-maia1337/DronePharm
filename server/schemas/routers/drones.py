# =============================================================================
# servidor/routers/drones.py
# =============================================================================

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from server.schemas.schemas import DroneCreate, DroneResponse
from bd.database import get_db
from bd.repositories.drone_repo import DroneRepository

router = APIRouter()


@router.post("/", response_model=DroneResponse, status_code=201, summary="Cadastrar drone")
async def cadastrar_drone(body: DroneCreate, db: AsyncSession = Depends(get_db)):
    repo = DroneRepository(db)
    if await repo.buscar_por_id(body.id):
        raise HTTPException(status_code=409, detail=f"Drone '{body.id}' já cadastrado.")
    return await repo.criar(**body.model_dump())


@router.get("/", summary="Listar drones")
async def listar_drones(db: AsyncSession = Depends(get_db)):
    repo   = DroneRepository(db)
    drones = await repo.listar()
    return {"total": len(drones), "drones": drones}


@router.get("/{drone_id}", response_model=DroneResponse, summary="Buscar drone")
async def buscar_drone(drone_id: str, db: AsyncSession = Depends(get_db)):
    repo  = DroneRepository(db)
    drone = await repo.buscar_por_id(drone_id)
    if not drone:
        raise HTTPException(status_code=404, detail=f"Drone '{drone_id}' não encontrado.")
    return drone


@router.patch("/{drone_id}/bateria", summary="Atualizar bateria do drone")
async def atualizar_bateria(drone_id: str, bateria_pct: float, db: AsyncSession = Depends(get_db)):
    if not (0.0 <= bateria_pct <= 1.0):
        raise HTTPException(status_code=422, detail="bateria_pct deve ser entre 0.0 e 1.0")
    repo = DroneRepository(db)
    await repo.atualizar_bateria(drone_id, bateria_pct)
    return {"drone_id": drone_id, "bateria_pct": bateria_pct}

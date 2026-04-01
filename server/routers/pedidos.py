# =============================================================================
# servidor/routers/pedidos.py
# CRUD completo de pedidos — /api/v1/pedidos
# =============================================================================

from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.schemas.schemas import (
    PedidoCreate, PedidoUpdate, PedidoResponse, PedidoListResponse
)
from bd.database import get_db
from bd.repositories.pedido_repo import PedidoRepository
from bd.repositories.farmacia_repo import FarmaciaRepository
from config.settings import PRIORIDADE_JANELA_H

router = APIRouter()


@router.post(
    "/",
    response_model=PedidoResponse,
    status_code=201,
    summary="Criar pedido de entrega",
    description=(
        "Registra um novo pedido de medicamento. "
        "A `janela_fim` é calculada automaticamente pela prioridade se não informada: "
        "P1=1h, P2=4h, P3=24h."
    ),
)
async def criar_pedido(body: PedidoCreate, db: AsyncSession = Depends(get_db)):
    # Valida farmácia
    farmacia_repo = FarmaciaRepository(db)
    farmacia      = await farmacia_repo.buscar_por_id(body.farmacia_id)
    if not farmacia:
        raise HTTPException(status_code=404, detail=f"Farmácia {body.farmacia_id} não encontrada.")
    if not farmacia.ativa:
        raise HTTPException(status_code=409, detail=f"Farmácia {body.farmacia_id} está inativa.")

    # Calcula janela_fim se não informada
    janela_fim = body.janela_fim
    if janela_fim is None:
        horas      = PRIORIDADE_JANELA_H.get(int(body.prioridade), 4.0)
        janela_fim = datetime.now() + timedelta(hours=horas)

    repo   = PedidoRepository(db)
    pedido = await repo.criar(
        latitude=body.coordenada.latitude,
        longitude=body.coordenada.longitude,
        peso_kg=body.peso_kg,
        prioridade=int(body.prioridade),
        descricao=body.descricao,
        farmacia_id=body.farmacia_id,
        janela_fim=janela_fim,
    )
    return pedido


@router.get(
    "/",
    response_model=PedidoListResponse,
    summary="Listar pedidos",
    description="Retorna pedidos com filtros opcionais por status, prioridade e farmácia.",
)
async def listar_pedidos(
    status:      Optional[str] = Query(None, description="pendente | em_rota | entregue | cancelado"),
    prioridade:  Optional[int] = Query(None, ge=1, le=3, description="1=Urgente 2=Normal 3=Reabastec"),
    farmacia_id: Optional[int] = Query(None),
    limite:      int           = Query(100, ge=1, le=500),
    offset:      int           = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    repo = PedidoRepository(db)
    total_count = await repo.contar(
        status=status,
        prioridade=prioridade,
        farmacia_id=farmacia_id,
    )
    pedidos = await repo.listar(
        status=status, prioridade=prioridade,
        farmacia_id=farmacia_id, limite=limite, offset=offset,
    )
    return {
        "total": len(pedidos),
        "pedidos": pedidos,
        "total_count": total_count,
        "limit": limite,
        "offset": offset,
        "has_more": offset + len(pedidos) < total_count,
    }


@router.get(
    "/pendentes",
    response_model=PedidoListResponse,
    summary="Listar pedidos pendentes",
    description="Retorna todos os pedidos com status 'pendente', ordenados por prioridade e tempo.",
)
async def listar_pendentes(db: AsyncSession = Depends(get_db)):
    repo    = PedidoRepository(db)
    pedidos = await repo.listar_pendentes()
    return {
        "total": len(pedidos),
        "pedidos": pedidos,
        "total_count": len(pedidos),
        "limit": len(pedidos),
        "offset": 0,
        "has_more": False,
    }


@router.get(
    "/{pedido_id}",
    response_model=PedidoResponse,
    summary="Buscar pedido por ID",
)
async def buscar_pedido(pedido_id: int, db: AsyncSession = Depends(get_db)):
    repo   = PedidoRepository(db)
    pedido = await repo.buscar_por_id(pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail=f"Pedido {pedido_id} não encontrado.")
    return pedido


@router.patch(
    "/{pedido_id}",
    response_model=PedidoResponse,
    summary="Atualizar pedido",
    description="Atualiza campos do pedido. Não é possível alterar pedidos já entregues.",
)
async def atualizar_pedido(
    pedido_id: int,
    body: PedidoUpdate,
    db: AsyncSession = Depends(get_db),
):
    repo   = PedidoRepository(db)
    pedido = await repo.buscar_por_id(pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail=f"Pedido {pedido_id} não encontrado.")
    if pedido.status == "entregue":
        raise HTTPException(status_code=409, detail="Pedidos entregues não podem ser modificados.")

    campos = body.model_dump(exclude_none=True)
    return await repo.atualizar(pedido_id, **campos)


@router.patch(
    "/{pedido_id}/cancelar",
    summary="Cancelar pedido",
    description="Cancela um pedido pendente. Pedidos em rota não podem ser cancelados.",
)
async def cancelar_pedido(pedido_id: int, db: AsyncSession = Depends(get_db)):
    repo   = PedidoRepository(db)
    pedido = await repo.buscar_por_id(pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail=f"Pedido {pedido_id} não encontrado.")
    if pedido.status == "em_rota":
        raise HTTPException(status_code=409, detail="Não é possível cancelar pedido já em rota.")
    if pedido.status in ("entregue", "cancelado"):
        raise HTTPException(status_code=409, detail=f"Pedido já está '{pedido.status}'.")
    await repo.atualizar_status(pedido_id, "cancelado")
    return {"mensagem": f"Pedido {pedido_id} cancelado.", "pedido_id": pedido_id}


@router.patch(
    "/{pedido_id}/entregar",
    summary="Marcar pedido como entregue",
    description="Confirma a entrega manual de um pedido (para testes ou ajuste operacional).",
)
async def entregar_pedido(pedido_id: int, db: AsyncSession = Depends(get_db)):
    repo   = PedidoRepository(db)
    pedido = await repo.buscar_por_id(pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail=f"Pedido {pedido_id} não encontrado.")
    if pedido.status == "entregue":
        raise HTTPException(status_code=409, detail="Pedido já está entregue.")
    await repo.atualizar_status(pedido_id, "entregue")
    return {"mensagem": f"Pedido {pedido_id} marcado como entregue.", "pedido_id": pedido_id}

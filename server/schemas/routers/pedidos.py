# =============================================================================
# servidor/routers/pedidos.py
# CRUD de pedidos — POST/GET/PATCH /api/v1/pedidos
# =============================================================================

from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.schemas.schemas import PedidoCreate, PedidoResponse, PedidoListResponse
from bd.database import get_db
from bd.repositories.pedido_repo import PedidoRepository
from config.settings import PRIORIDADE_JANELA_H

router = APIRouter()


@router.post("/", response_model=PedidoResponse, status_code=201, summary="Criar pedido")
async def criar_pedido(body: PedidoCreate, db: AsyncSession = Depends(get_db)):
    """
    Registra um novo pedido de medicamento.
    A janela de entrega é calculada automaticamente pela prioridade se não informada.
    """
    repo = PedidoRepository(db)

    # Calcula janela_fim se não informada
    janela_fim = body.janela_fim
    if janela_fim is None:
        horas     = PRIORIDADE_JANELA_H.get(body.prioridade, 4.0)
        janela_fim = datetime.now() + timedelta(hours=horas)

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


@router.get("/", response_model=PedidoListResponse, summary="Listar pedidos")
async def listar_pedidos(
    status:      Optional[str] = Query(None, description="pendente | em_rota | entregue | cancelado"),
    prioridade:  Optional[int] = Query(None, ge=1, le=3),
    farmacia_id: Optional[int] = Query(None),
    limite:      int           = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    repo    = PedidoRepository(db)
    pedidos = await repo.listar(status=status, prioridade=prioridade,
                                farmacia_id=farmacia_id, limite=limite)
    return {"total": len(pedidos), "pedidos": pedidos}


@router.get("/pendentes", response_model=PedidoListResponse, summary="Listar pedidos pendentes")
async def listar_pendentes(db: AsyncSession = Depends(get_db)):
    repo    = PedidoRepository(db)
    pedidos = await repo.listar_pendentes()
    return {"total": len(pedidos), "pedidos": pedidos}


@router.get("/{pedido_id}", response_model=PedidoResponse, summary="Buscar pedido por ID")
async def buscar_pedido(pedido_id: int, db: AsyncSession = Depends(get_db)):
    repo   = PedidoRepository(db)
    pedido = await repo.buscar_por_id(pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail=f"Pedido {pedido_id} não encontrado.")
    return pedido


@router.patch("/{pedido_id}/cancelar", summary="Cancelar pedido")
async def cancelar_pedido(pedido_id: int, db: AsyncSession = Depends(get_db)):
    repo   = PedidoRepository(db)
    pedido = await repo.buscar_por_id(pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail=f"Pedido {pedido_id} não encontrado.")
    if pedido.status == "em_rota":
        raise HTTPException(status_code=409, detail="Não é possível cancelar pedido já em rota.")

    await repo.atualizar_status(pedido_id, "cancelado")
    return {"mensagem": f"Pedido {pedido_id} cancelado.", "pedido_id": pedido_id}

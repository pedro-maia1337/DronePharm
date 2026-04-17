# =============================================================================
# servidor/routers/pedidos.py
# CRUD completo de pedidos — /api/v1/pedidos
# =============================================================================

from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from server.schemas.schemas import (
    PedidoAtivoResponse, PedidoCreate, PedidoUpdate, PedidoResponse, PedidoListResponse
)
from bd.database import get_db
from bd.repositories.pedido_repo import PedidoRepository
from bd.repositories.farmacia_repo import FarmaciaRepository
from config.settings import ORQUESTRACAO_APOS_PEDIDO, PRIORIDADE_JANELA_H
from server.services.orquestracao_pedido import tarefa_background_orquestrar_pedido
from server.services.pedido_tracking import obter_pedido_ativo
from server.security.rest_auth import require_rest_admin, require_rest_write
from domain.pedido_estado import (
    OperacaoTransicaoPedido,
    StatusPedido,
    TransicaoPedidoInvalidaError,
)

router = APIRouter()


@router.post(
    "/",
    response_model=PedidoResponse,
    status_code=201,
    summary="Criar pedido de entrega",
    description=(
        "Registra um novo pedido de medicamento. "
        "A `janela_fim` é calculada automaticamente pela prioridade se não informada: "
        "P1=1h, P2=4h, P3=24h. "
        "Com `ORQUESTRACAO_APOS_PEDIDO=true`, agenda roteirização automática em background."
    ),
)
async def criar_pedido(
    body: PedidoCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_rest_write),
):
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
    if ORQUESTRACAO_APOS_PEDIDO:
        background_tasks.add_task(tarefa_background_orquestrar_pedido, pedido.id)
    return pedido


@router.get(
    "/",
    response_model=PedidoListResponse,
    summary="Listar pedidos",
    description="Retorna pedidos com filtros opcionais por status, prioridade e farmácia.",
)
async def listar_pedidos(
    status:      Optional[str] = Query(
        None,
        description=(
            "pendente | calculado | despachado | em_voo | entregue | cancelado | falha"
        ),
    ),
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


@router.get(
    "/{pedido_id}/ativo",
    response_model=PedidoAtivoResponse,
    summary="Acompanhamento enriquecido de pedido ativo",
    description=(
        "Retorna o payload consolidado de acompanhamento do pedido em tempo real, "
        "incluindo rota, drone, ETA, tempos e posição GPS atual."
    ),
)
async def buscar_pedido_ativo(pedido_id: int, db: AsyncSession = Depends(get_db)):
    payload = await obter_pedido_ativo(db, pedido_id)
    if not payload:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Pedido {pedido_id} não está ativo para acompanhamento "
                "(esperado: calculado, despachado ou em_voo)."
            ),
        )
    return payload


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
    _auth=Depends(require_rest_write),
):
    repo   = PedidoRepository(db)
    pedido = await repo.buscar_por_id(pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail=f"Pedido {pedido_id} não encontrado.")
    if pedido.status in (StatusPedido.ENTREGUE, StatusPedido.CANCELADO, StatusPedido.FALHA):
        raise HTTPException(
            status_code=409,
            detail=f"Pedidos com status '{pedido.status}' não podem ser modificados.",
        )

    campos = body.model_dump(exclude_none=True)
    try:
        return await repo.atualizar(pedido_id, **campos)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/{pedido_id}/cancelar",
    summary="Cancelar pedido",
    description=(
        "Cancela um pedido em `pendente` ou `calculado`. "
        "Pedidos já despachados ou em voo não podem ser cancelados por este endpoint."
    ),
)
async def cancelar_pedido(
    pedido_id: int,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_rest_write),
):
    repo   = PedidoRepository(db)
    pedido = await repo.buscar_por_id(pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail=f"Pedido {pedido_id} não encontrado.")
    if pedido.status in (StatusPedido.ENTREGUE, StatusPedido.CANCELADO):
        raise HTTPException(status_code=409, detail=f"Pedido já está '{pedido.status}'.")
    try:
        await repo.atualizar_status(
            pedido_id,
            StatusPedido.CANCELADO,
            operacao=OperacaoTransicaoPedido.API_CANCELAR,
        )
    except TransicaoPedidoInvalidaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"mensagem": f"Pedido {pedido_id} cancelado.", "pedido_id": pedido_id}


@router.patch(
    "/{pedido_id}/entregar",
    summary="Marcar pedido como entregue",
    description=(
        "Confirma a entrega manual quando o pedido está `em_voo` "
        "(ajuste operacional ou confirmação no destino)."
    ),
)
async def entregar_pedido(
    pedido_id: int,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_rest_admin),
):
    repo   = PedidoRepository(db)
    pedido = await repo.buscar_por_id(pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail=f"Pedido {pedido_id} não encontrado.")
    if pedido.status == StatusPedido.ENTREGUE:
        raise HTTPException(status_code=409, detail="Pedido já está entregue.")
    try:
        await repo.atualizar_status(
            pedido_id,
            StatusPedido.ENTREGUE,
            operacao=OperacaoTransicaoPedido.API_ENTREGAR,
        )
    except TransicaoPedidoInvalidaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"mensagem": f"Pedido {pedido_id} marcado como entregue.", "pedido_id": pedido_id}

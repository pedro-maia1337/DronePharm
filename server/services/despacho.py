from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from bd.repositories.drone_repo import DroneRepository
from bd.repositories.pedido_repo import PedidoRepository
from bd.repositories.rota_repo import RotaRepository
from domain.pedido_estado import OperacaoTransicaoPedido, StatusPedido
from server.services.simulacao_voo import (
    emitir_primeiro_frame_rota,
    iniciar_simulacao_rota_em_background,
)

_STATUS_ROTAS_DESPACHAVEIS = frozenset({"calculada", "criada", "pendente"})
_STATUS_ROTAS_JA_INICIADAS = frozenset({"em_execucao", "concluida", "abortada"})


async def despachar_rota(db: AsyncSession, rota_id: int) -> Dict[str, Any]:
    """
    Inicia a execução física de uma rota.

    A transação é executada sobre a mesma AsyncSession da request; caso
    qualquer etapa falhe, o rollback automático de `get_db()` preserva a
    atomicidade entre rota, pedidos e drone.
    """
    rota_repo = RotaRepository(db)
    pedido_repo = PedidoRepository(db)
    drone_repo = DroneRepository(db)

    rota = await rota_repo.buscar_por_id(rota_id)
    if not rota:
        raise HTTPException(status_code=404, detail=f"Rota {rota_id} não encontrada.")

    if rota.status in _STATUS_ROTAS_JA_INICIADAS:
        raise HTTPException(
            status_code=400,
            detail=f"Rota {rota_id} não pode ser despachada com status '{rota.status}'.",
        )
    if rota.status not in _STATUS_ROTAS_DESPACHAVEIS:
        raise HTTPException(
            status_code=400,
            detail=f"Status '{rota.status}' não permite despacho da rota {rota_id}.",
        )

    pedido_ids = rota.pedido_ids or []
    if not pedido_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Rota {rota_id} não possui pedidos associados para despacho.",
        )

    pedidos = await pedido_repo.buscar_por_ids(pedido_ids)
    if len(pedidos) != len(pedido_ids):
        raise HTTPException(
            status_code=400,
            detail=f"Rota {rota_id} possui pedidos inválidos ou ausentes para despacho.",
        )

    await rota_repo.atualizar_status(rota_id, "em_execucao")
    await pedido_repo.atualizar_status_lote(
        ids=pedido_ids,
        status=StatusPedido.DESPACHADO,
        operacao=OperacaoTransicaoPedido.ROTAS_DESPACHAR,
        rota_id=rota_id,
        drone_id=rota.drone_id,
    )
    await drone_repo.atualizar(rota.drone_id, status="em_voo")
    await db.flush()

    return {
        "mensagem": f"Rota {rota_id} despachada com sucesso.",
        "rota_id": rota_id,
        "drone_id": rota.drone_id,
        "status_rota": "em_execucao",
        "status_pedidos": StatusPedido.DESPACHADO,
        "pedidos_despachados": pedido_ids,
    }


async def forcar_inicio_voo(db: AsyncSession, rota_id: int) -> Dict[str, Any]:
    resultado = await despachar_rota(db, rota_id)
    await db.commit()

    await emitir_primeiro_frame_rota(rota_id)
    simulacao_iniciada = iniciar_simulacao_rota_em_background(
        rota_id,
        emitir_frame_inicial=False,
    )

    resultado.update(
        {
            "mensagem": f"Rota {rota_id} iniciou simulacao imediata.",
            "simulacao_iniciada": simulacao_iniciada,
            "primeiro_frame_emitido": True,
        }
    )
    return resultado

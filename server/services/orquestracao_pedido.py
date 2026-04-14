# =============================================================================
# server/services/orquestracao_pedido.py
# Fase B — após criar pedido, agenda roteirização com drone elegível (background).
# =============================================================================
from __future__ import annotations

import logging

from bd.database import AsyncSessionLocal
from bd.repositories.pedido_repo import PedidoRepository
from bd.repositories.drone_repo import DroneRepository
from domain.pedido_estado import StatusPedido

log = logging.getLogger(__name__)


def _eh_resposta_http_starlette(exc: BaseException) -> bool:
    """Detecta HTTPException do Starlette/FastAPI sem import obrigatório."""
    return getattr(exc, "status_code", None) is not None and hasattr(exc, "detail")


async def executar_orquestracao_novo_pedido(pedido_id: int) -> None:
    """
    Seleciona o drone disponível com maior bateria e calcula rota só para este pedido.
    Falhas de clima, drone indisponível ou concorrência são registradas em log;
    o pedido permanece `pendente` para nova tentativa manual (POST /rotas/calcular).
    """
    async with AsyncSessionLocal() as session:
        try:
            pedido_repo = PedidoRepository(session)
            pedido = await pedido_repo.buscar_por_id(pedido_id)
            if not pedido or pedido.status != StatusPedido.PENDENTE:
                log.debug(
                    "Orquestração pedido %s ignorada (ausente ou não pendente).",
                    pedido_id,
                )
                return

            drone_repo = DroneRepository(session)
            disponiveis = await drone_repo.buscar_disponiveis()
            if not disponiveis:
                log.warning(
                    "Orquestração: nenhum drone em 'aguardando' para pedido %s.",
                    pedido_id,
                )
                return

            drone = disponiveis[0]

            # Import tardio: evita carregar o grafo pesado da roteirização no import do módulo.
            from server.services.roteirizacao_service import calcular_rotas_para_pedidos

            await calcular_rotas_para_pedidos(
                session,
                pedido_ids=[pedido_id],
                drone_id=drone.id,
                forcar_recalc=False,
                vento_ms=None,
            )
            await session.commit()
            log.info(
                "Orquestração: pedido %s roteirizado com drone %s.",
                pedido_id,
                drone.id,
            )
        except Exception as exc:
            await session.rollback()
            if _eh_resposta_http_starlette(exc):
                log.warning(
                    "Orquestração pedido %s não concluída: %s",
                    pedido_id,
                    getattr(exc, "detail", exc),
                )
            else:
                log.exception("Orquestração: falha inesperada no pedido %s.", pedido_id)


async def tarefa_background_orquestrar_pedido(pedido_id: int) -> None:
    """Entrada para FastAPI BackgroundTasks."""
    await executar_orquestracao_novo_pedido(pedido_id)

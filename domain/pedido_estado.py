# =============================================================================
# domain/pedido_estado.py
# Máquina de estados dos pedidos — Fase A (transições centralizadas)
# =============================================================================
from __future__ import annotations

from enum import Enum
from typing import FrozenSet, Optional, Tuple

# Status canônicos (string no banco — coluna VARCHAR)
class StatusPedido:
    PENDENTE = "pendente"
    CALCULADO = "calculado"
    DESPACHADO = "despachado"
    EM_VOO = "em_voo"
    ENTREGUE = "entregue"
    CANCELADO = "cancelado"
    FALHA = "falha"


TODOS_STATUS: FrozenSet[str] = frozenset(
    {
        StatusPedido.PENDENTE,
        StatusPedido.CALCULADO,
        StatusPedido.DESPACHADO,
        StatusPedido.EM_VOO,
        StatusPedido.ENTREGUE,
        StatusPedido.CANCELADO,
        StatusPedido.FALHA,
    }
)

STATUS_TERMINAIS: FrozenSet[str] = frozenset(
    {StatusPedido.ENTREGUE, StatusPedido.CANCELADO, StatusPedido.FALHA}
)

# Pedidos que ainda aparecem como “em andamento” no mapa / operações
STATUS_ATIVOS_MAPA: Tuple[str, ...] = (
    StatusPedido.PENDENTE,
    StatusPedido.CALCULADO,
    StatusPedido.DESPACHADO,
    StatusPedido.EM_VOO,
)


class OperacaoTransicaoPedido(str, Enum):
    """Quem dispara a mudança de estado (usado na validação central)."""

    ROTAS_CALCULAR = "rotas_calcular"      # pendente → calculado (lote)
    ROTAS_CONCLUIR = "rotas_concluir"      # calculado|despachado|em_voo → entregue
    ROTAS_ABORTAR = "rotas_abortar"        # calculado|despachado|em_voo → pendente
    API_CANCELAR = "api_cancelar"          # pendente|calculado → cancelado
    API_ENTREGAR = "api_entregar"          # em_voo → entregue
    TELEM_DESPACHO = "telem_despacho"      # calculado → despachado (missão ativa / telemetria)
    TELEM_EM_VOO = "telem_em_voo"          # despachado → em_voo (movimento confirmado)
    SISTEMA_INTERNO = "sistema_interno"    # reservado


class TransicaoPedidoInvalidaError(ValueError):
    """Transição de status não permitida pela máquina de estados."""

    def __init__(self, origem: str, destino: str, operacao: str, mensagem: Optional[str] = None):
        self.origem = origem
        self.destino = destino
        self.operacao = operacao
        detail = mensagem or (
            f"Transição de status inválida: '{origem}' → '{destino}' "
            f"(operação={operacao})."
        )
        super().__init__(detail)


def _par_valido(origem: str, destino: str, operacao: OperacaoTransicaoPedido) -> bool:
    o, d = origem, destino
    if operacao == OperacaoTransicaoPedido.ROTAS_CALCULAR:
        return o == StatusPedido.PENDENTE and d == StatusPedido.CALCULADO
    if operacao == OperacaoTransicaoPedido.ROTAS_CONCLUIR:
        return o in (
            StatusPedido.CALCULADO,
            StatusPedido.DESPACHADO,
            StatusPedido.EM_VOO,
        ) and d == StatusPedido.ENTREGUE
    if operacao == OperacaoTransicaoPedido.ROTAS_ABORTAR:
        return o in (
            StatusPedido.CALCULADO,
            StatusPedido.DESPACHADO,
            StatusPedido.EM_VOO,
        ) and d == StatusPedido.PENDENTE
    if operacao == OperacaoTransicaoPedido.API_CANCELAR:
        return o in (StatusPedido.PENDENTE, StatusPedido.CALCULADO) and d == StatusPedido.CANCELADO
    if operacao == OperacaoTransicaoPedido.API_ENTREGAR:
        return o == StatusPedido.EM_VOO and d == StatusPedido.ENTREGUE
    if operacao == OperacaoTransicaoPedido.TELEM_DESPACHO:
        return o == StatusPedido.CALCULADO and d == StatusPedido.DESPACHADO
    if operacao == OperacaoTransicaoPedido.TELEM_EM_VOO:
        return o == StatusPedido.DESPACHADO and d == StatusPedido.EM_VOO
    if operacao == OperacaoTransicaoPedido.SISTEMA_INTERNO:
        return False
    return False


def validar_transicao_pedido(
    origem: str,
    destino: str,
    operacao: OperacaoTransicaoPedido,
) -> None:
    """
    Garante que apenas transições válidas sejam persistidas.
    Levanta TransicaoPedidoInvalidaError com mensagem adequada para HTTP 409.
    """
    if origem == destino:
        raise TransicaoPedidoInvalidaError(
            origem, destino, operacao.value, "O novo status é igual ao atual."
        )
    if not _par_valido(origem, destino, operacao):
        raise TransicaoPedidoInvalidaError(origem, destino, operacao.value)


def legado_em_rota_para_calculado(status: str) -> str:
    """Normaliza valor antigo `em_rota` (pré–Fase A) para `calculado`."""
    if status == "em_rota":
        return StatusPedido.CALCULADO
    return status

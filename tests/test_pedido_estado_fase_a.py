# =============================================================================
# tests/test_pedido_estado_fase_a.py
# Validação da Fase A — máquina de estados de pedidos (sem alterar suites existentes)
# =============================================================================
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain.pedido_estado import (
    OperacaoTransicaoPedido,
    StatusPedido,
    TransicaoPedidoInvalidaError,
    legado_em_rota_para_calculado,
    validar_transicao_pedido,
)


class TestDominioTransicoes:
    def test_rotas_calcular_apenas_pendente_para_calculado(self):
        validar_transicao_pedido(
            StatusPedido.PENDENTE,
            StatusPedido.CALCULADO,
            OperacaoTransicaoPedido.ROTAS_CALCULAR,
        )
        with pytest.raises(TransicaoPedidoInvalidaError):
            validar_transicao_pedido(
                StatusPedido.CALCULADO,
                StatusPedido.CALCULADO,
                OperacaoTransicaoPedido.ROTAS_CALCULAR,
            )
        with pytest.raises(TransicaoPedidoInvalidaError):
            validar_transicao_pedido(
                StatusPedido.PENDENTE,
                StatusPedido.CALCULADO,
                OperacaoTransicaoPedido.API_CANCELAR,
            )

    def test_api_cancelar_pendente_ou_calculado(self):
        validar_transicao_pedido(
            StatusPedido.PENDENTE,
            StatusPedido.CANCELADO,
            OperacaoTransicaoPedido.API_CANCELAR,
        )
        validar_transicao_pedido(
            StatusPedido.CALCULADO,
            StatusPedido.CANCELADO,
            OperacaoTransicaoPedido.API_CANCELAR,
        )
        with pytest.raises(TransicaoPedidoInvalidaError):
            validar_transicao_pedido(
                StatusPedido.EM_VOO,
                StatusPedido.CANCELADO,
                OperacaoTransicaoPedido.API_CANCELAR,
            )

    def test_api_entregar_apenas_de_em_voo(self):
        validar_transicao_pedido(
            StatusPedido.EM_VOO,
            StatusPedido.ENTREGUE,
            OperacaoTransicaoPedido.API_ENTREGAR,
        )
        with pytest.raises(TransicaoPedidoInvalidaError):
            validar_transicao_pedido(
                StatusPedido.CALCULADO,
                StatusPedido.ENTREGUE,
                OperacaoTransicaoPedido.API_ENTREGAR,
            )

    def test_rotas_concluir_de_calculado_ou_em_voo(self):
        for origem in (
            StatusPedido.CALCULADO,
            StatusPedido.DESPACHADO,
            StatusPedido.EM_VOO,
        ):
            validar_transicao_pedido(
                origem,
                StatusPedido.ENTREGUE,
                OperacaoTransicaoPedido.ROTAS_CONCLUIR,
            )

    def test_rotas_abortar_restaura_pendente(self):
        validar_transicao_pedido(
            StatusPedido.CALCULADO,
            StatusPedido.PENDENTE,
            OperacaoTransicaoPedido.ROTAS_ABORTAR,
        )

    def test_mesmo_status_levanta(self):
        with pytest.raises(TransicaoPedidoInvalidaError):
            validar_transicao_pedido(
                StatusPedido.PENDENTE,
                StatusPedido.PENDENTE,
                OperacaoTransicaoPedido.API_CANCELAR,
            )

    def test_normaliza_legado_em_rota(self):
        assert legado_em_rota_para_calculado("em_rota") == StatusPedido.CALCULADO
        assert legado_em_rota_para_calculado("pendente") == "pendente"

    def test_telem_despacho_calculado_para_despachado(self):
        validar_transicao_pedido(
            StatusPedido.CALCULADO,
            StatusPedido.DESPACHADO,
            OperacaoTransicaoPedido.TELEM_DESPACHO,
        )

    def test_telem_em_voo_despachado_para_em_voo(self):
        validar_transicao_pedido(
            StatusPedido.DESPACHADO,
            StatusPedido.EM_VOO,
            OperacaoTransicaoPedido.TELEM_EM_VOO,
        )

# =============================================================================
# constraints/verificador.py
# Verificação de todas as restrições operacionais antes de validar uma rota
# =============================================================================

from __future__ import annotations
from dataclasses import dataclass
from typing import List

from models.pedido import Pedido
from models.drone import Drone
from algorithms.distancia import distancia_rota
from algorithms.custo import estimar_tempo_rota_s, estimar_energia_wh
from config.settings import (
    DRONE_BATERIA_MINIMA, VENTO_MAX_OPERACIONAL_MS,
    GA_PENALIDADE_CAPACIDADE, GA_PENALIDADE_AUTONOMIA, GA_PENALIDADE_PRIORIDADE,
)


@dataclass
class ResultadoVerificacao:
    """Resultado detalhado da verificação de restrições de uma rota."""
    viavel:              bool
    viola_capacidade:    bool  = False
    viola_autonomia:     bool  = False
    viola_prioridade:    bool  = False
    viola_vento:         bool  = False
    carga_total_kg:      float = 0.0
    distancia_total_km:  float = 0.0
    penalidade_total:    float = 0.0
    mensagens:           List[str] = None

    def __post_init__(self):
        if self.mensagens is None:
            self.mensagens = []

    def __repr__(self) -> str:
        status = "✓ Viável" if self.viavel else "✗ Inviável"
        msgs   = " | ".join(self.mensagens) if self.mensagens else "Sem restrições violadas"
        return f"[{status}] {msgs} | Penalidade: {self.penalidade_total:.0f}"


class Verificador:
    """
    Verifica se uma rota (sequência de índices de pedidos) satisfaz
    todas as restrições operacionais do drone.

    Uso
    ---
    verificador = Verificador(drone, pedidos, matriz)
    resultado   = verificador.verificar(sequencia)
    if resultado.viavel:
        ...
    """

    def __init__(self, drone: Drone, pedidos: List[Pedido], matriz):
        self.drone       = drone
        self.pedidos     = pedidos
        self.matriz      = matriz
        # Mapa índice-matriz (1-based) → Pedido
        self.pedidos_mapa = {i + 1: p for i, p in enumerate(pedidos)}

    # ------------------------------------------------------------------
    def verificar(self, sequencia: List[int], vento_ms: float = 0.0) -> ResultadoVerificacao:
        """
        Executa todas as verificações de restrição para a sequência fornecida.

        Parâmetros
        ----------
        sequencia : lista de índices 1-based dos pedidos
        vento_ms  : velocidade do vento para ajuste de autonomia

        Retorna
        -------
        ResultadoVerificacao com detalhes de cada restrição
        """
        resultado = ResultadoVerificacao(viavel=True)

        self._checar_capacidade(sequencia, resultado)
        self._checar_autonomia(sequencia, resultado, vento_ms)
        self._checar_prioridade(sequencia, resultado)
        self._checar_vento(resultado, vento_ms)

        resultado.viavel = resultado.penalidade_total == 0.0
        return resultado

    # ------------------------------------------------------------------
    def penalidade(self, sequencia: List[int], vento_ms: float = 0.0) -> float:
        """
        Retorna apenas o valor numérico de penalidade total.
        Usado diretamente pela função de fitness do Algoritmo Genético.
        """
        return self.verificar(sequencia, vento_ms).penalidade_total

    # ------------------------------------------------------------------
    def _checar_capacidade(self, sequencia: List[int], resultado: ResultadoVerificacao):
        """Verifica se a carga total não excede a capacidade do drone."""
        pedidos_rota  = [self.pedidos_mapa[i] for i in sequencia if i in self.pedidos_mapa]
        carga_total   = sum(p.peso_kg for p in pedidos_rota)
        resultado.carga_total_kg = carga_total

        if carga_total > self.drone.capacidade_max_kg:
            excesso = carga_total - self.drone.capacidade_max_kg
            resultado.viola_capacidade  = True
            resultado.penalidade_total += GA_PENALIDADE_CAPACIDADE
            resultado.mensagens.append(
                f"Capacidade excedida em {excesso:.2f}kg "
                f"({carga_total:.2f}/{self.drone.capacidade_max_kg}kg)"
            )

    def _checar_autonomia(
        self, sequencia: List[int],
        resultado: ResultadoVerificacao,
        vento_ms: float
    ):
        """Verifica se a distância total está dentro da autonomia do drone."""
        dist_km = distancia_rota(sequencia, self.matriz)
        resultado.distancia_total_km = dist_km
        autonomia = self.drone.autonomia_com_vento_km(vento_ms)

        if dist_km > autonomia:
            excesso = dist_km - autonomia
            resultado.viola_autonomia   = True
            resultado.penalidade_total += GA_PENALIDADE_AUTONOMIA
            resultado.mensagens.append(
                f"Autonomia excedida em {excesso:.2f}km "
                f"({dist_km:.2f}/{autonomia:.2f}km)"
            )

    def _checar_prioridade(self, sequencia: List[int], resultado: ResultadoVerificacao):
        """Verifica se pedidos urgentes podem ser atendidos no prazo."""
        from datetime import datetime
        tempo_estimado_s = estimar_tempo_rota_s(sequencia, self.matriz)
        agora = datetime.now()

        for idx in sequencia:
            pedido = self.pedidos_mapa.get(idx)
            if pedido is None or pedido.janela_fim is None:
                continue
            tempo_restante = (pedido.janela_fim - agora).total_seconds()
            if tempo_estimado_s > tempo_restante and pedido.urgente:
                resultado.viola_prioridade  = True
                resultado.penalidade_total += GA_PENALIDADE_PRIORIDADE
                resultado.mensagens.append(
                    f"Pedido urgente #{pedido.id} fora da janela "
                    f"(precisa de {tempo_estimado_s:.0f}s, restam {tempo_restante:.0f}s)"
                )

    def _checar_vento(self, resultado: ResultadoVerificacao, vento_ms: float):
        """Verifica condição de vento para operação segura."""
        if vento_ms > VENTO_MAX_OPERACIONAL_MS:
            resultado.viola_vento       = True
            resultado.penalidade_total += GA_PENALIDADE_AUTONOMIA  # Penalidade igual à autonomia
            resultado.mensagens.append(
                f"Vento acima do limite operacional: {vento_ms:.1f}m/s "
                f"(máx: {VENTO_MAX_OPERACIONAL_MS}m/s)"
            )

# =============================================================================
# algorithms/clarke_wright.py
# Fase 1 — Heurística Construtiva: Clarke-Wright Savings Algorithm
#
# Gera a solução inicial agrupando pedidos em rotas que minimizam
# a distância total percorrida, respeitando restrições do drone.
# =============================================================================

from __future__ import annotations
from typing import List, Dict, Tuple
import logging

import numpy as np

from models.pedido import Pedido
from models.drone import Drone
from models.rota import Rota, Waypoint
from algorithms.distancia import (
    construir_matriz_distancias, calcular_todos_savings, distancia_rota
)
from algorithms.custo import calcular_custo_detalhado, estimar_tempo_rota_s
from constraints.verificador import Verificador

log = logging.getLogger(__name__)


class ClarkeWright:
    """
    Implementação do algoritmo de Clarke-Wright para geração de rotas iniciais.

    O algoritmo parte de N rotas individuais (depósito → pedido_i → depósito)
    e iterativamente combina pares de rotas quando isso reduz a distância total
    (saving positivo) sem violar as restrições do drone.

    Uso
    ---
    cw = ClarkeWright(drone, pedidos)
    rotas = cw.resolver()
    """

    def __init__(self, drone: Drone, pedidos: List[Pedido], vento_ms: float = 0.0):
        self.drone     = drone
        self.pedidos   = pedidos
        self.vento_ms  = vento_ms
        self.n         = len(pedidos)

        # Monta matriz e mapa de pedidos (índice 0 = depósito, 1..N = pedidos)
        self.matriz        = construir_matriz_distancias(pedidos, incluir_deposito=True)
        self.pedidos_mapa  = {i + 1: p for i, p in enumerate(pedidos)}
        self.verificador   = Verificador(drone, pedidos, self.matriz)

        log.info(f"Clarke-Wright iniciado: {self.n} pedidos | Drone: {drone.nome}")

    # ------------------------------------------------------------------
    def resolver(self) -> List[List[int]]:
        """
        Executa o algoritmo Clarke-Wright e retorna uma lista de rotas.
        Cada rota é uma lista de índices 1-based (sem o depósito).

        Retorna
        -------
        List[List[int]]
            Ex: [[1, 3], [2], [4, 5]] = 3 voos necessários
        """
        if self.n == 0:
            return []

        # ------------------------------------------------------------------
        # PASSO 1: Inicializa com uma rota individual por pedido
        # ------------------------------------------------------------------
        # rotas: lista de listas de índices
        rotas: List[List[int]] = [[i + 1] for i in range(self.n)]

        log.debug(f"Rotas iniciais: {len(rotas)} rotas individuais")

        # ------------------------------------------------------------------
        # PASSO 2: Calcula todos os savings e ordena do maior para o menor
        # ------------------------------------------------------------------
        savings = calcular_todos_savings(self.n, self.matriz)
        log.debug(f"Savings calculados: {len(savings)} pares")

        # ------------------------------------------------------------------
        # PASSO 3: Itera pelos savings e combina rotas quando factível
        # ------------------------------------------------------------------
        for s_val, i, j in savings:
            if s_val <= 0:
                break   # Lista ordenada: savings abaixo de zero não valem

            rota_i = self._encontrar_rota(rotas, i)
            rota_j = self._encontrar_rota(rotas, j)

            # Não combina se i e j já estão na mesma rota
            if rota_i is None or rota_j is None or rota_i is rota_j:
                continue

            # Verifica se i é o último da sua rota e j é o primeiro da outra
            # (restrição de extremidade do Clarke-Wright)
            if not self._podem_combinar(rota_i, rota_j, i, j):
                continue

            rota_candidata = self._combinar(rota_i, rota_j, i, j)
            resultado = self.verificador.verificar(rota_candidata, self.vento_ms)

            if resultado.viavel:
                rotas.remove(rota_i)
                rotas.remove(rota_j)
                rotas.append(rota_candidata)
                log.debug(f"Combinadas rotas {rota_i} + {rota_j} → {rota_candidata} (saving={s_val:.3f})")

        log.info(f"Clarke-Wright concluído: {len(rotas)} rotas necessárias")
        return rotas

    # ------------------------------------------------------------------
    def para_objetos_rota(self, sequencias: List[List[int]]) -> List[Rota]:
        """
        Converte as sequências de índices em objetos Rota completos
        com waypoints, métricas e status de viabilidade.
        """
        rotas_obj = []
        for seq in sequencias:
            rota = Rota()
            rota.adicionar_waypoint(Rota.deposito_waypoint())

            pedidos_rota = [self.pedidos_mapa[i] for i in seq]
            for p in pedidos_rota:
                rota.adicionar_waypoint(
                    Waypoint(coordenada=p.coordenada, pedido=p)
                )
            rota.adicionar_waypoint(Rota.deposito_waypoint())

            metricas = calcular_custo_detalhado(
                seq, self.matriz, self.pedidos_mapa,
                carga_kg=rota.carga_total_kg, vento_ms=self.vento_ms
            )
            rota.distancia_total_km = metricas["distancia_km"]
            rota.tempo_total_s      = metricas["tempo_min"] * 60
            rota.energia_wh         = metricas["energia_wh"]
            rota.custo              = metricas["custo_total"]
            rota.viavel             = self.verificador.verificar(seq, self.vento_ms).viavel

            rotas_obj.append(rota)

        return rotas_obj

    # ------------------------------------------------------------------
    # Métodos auxiliares internos
    # ------------------------------------------------------------------

    def _encontrar_rota(self, rotas: List[List[int]], idx: int) -> List[int] | None:
        """Encontra qual rota contém o índice idx."""
        for rota in rotas:
            if idx in rota:
                return rota
        return None

    def _podem_combinar(
        self,
        rota_i: List[int],
        rota_j: List[int],
        i: int, j: int
    ) -> bool:
        """
        No Clarke-Wright paralelo, i deve ser a extremidade de rota_i
        e j deve ser a extremidade de rota_j para que a combinação seja válida.
        """
        return (
            (rota_i[-1] == i and rota_j[0] == j) or
            (rota_i[0]  == i and rota_j[-1] == j) or
            (rota_i[-1] == i and rota_j[-1] == j) or
            (rota_i[0]  == i and rota_j[0]  == j)
        )

    def _combinar(
        self,
        rota_i: List[int],
        rota_j: List[int],
        i: int, j: int
    ) -> List[int]:
        """Combina duas rotas de forma que i preceda j na rota resultante."""
        ri = list(rota_i)
        rj = list(rota_j)

        # Garante que i esteja no final de ri e j no início de rj
        if ri[0] == i:
            ri = ri[::-1]          # Inverte rota_i
        if rj[-1] == j:
            rj = rj[::-1]          # Inverte rota_j

        return ri + rj
